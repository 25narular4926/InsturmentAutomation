#!/usr/bin/env python3
"""Find Tektronix oscilloscopes on the LAN and open sessions to all of them.

Two ways to discover, both feeding the same *IDN? confirmation step:
  - mDNS / LXI (the proper LXI way): scopes advertise themselves over multicast DNS,
    so they are found anywhere on the LAN with no subnet needed. Uses the 'zeroconf'
    package (pip install zeroconf) - pure Python, no vendor VISA.
  - Subnet scan (pure stdlib, no installs): scan a /24 in parallel for the SCPI port.
    Reliable on a switch with static IPs; a good fallback if mDNS is blocked.

Either way, each candidate IP is confirmed by opening a socket, sending *IDN?, and
keeping the ones that answer as a Tektronix scope. ScopeFleet then opens a SocketScope
session to every discovered scope and lets you drive them together.

  python discovery.py                         # mDNS discover + list scopes
  python discovery.py --subnet 192.168.1.0/24 # scan a subnet instead
  python discovery.py --open                   # discover, open all, print each *IDN?
"""

from __future__ import annotations

import argparse
import socket
import sys
import time

# Same folder: reuse the transport and the configure/capture engine.
import os
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import bench_socket as bs  # noqa: E402

# Ports a Tektronix scope may answer SCPI on: 4000 = Tek Socket Server (Terminal mode),
# 5025 = LXI raw SCPI socket. We try each until *IDN? comes back.
DEFAULT_PORTS = (4000, 5025)

# Instrument vendors we know how to drive (scopes AND function generators live here).
_INSTRUMENT_VENDORS = ("TEKTRONIX", "KEYSIGHT", "AGILENT")
# Oscilloscope model families, both brands: MSO/MSOX, DPO, MDO, TDS, TBS, DSO/DSOX, EDUX.
_SCOPE_FAMILIES = ("MSO", "DPO", "MDO", "TDS", "TBS", "DSO", "EDUX")
# Function-generator / AWG model families: Tektronix AFG/AWG, Keysight 332xx/335xx/336xx
# (e.g. 33210A, 33220A, 33250A, 33509B..33522A, 33611A..33622A). 4-digit prefixes match the
# real model strings without being as loose as a bare "33".
_AFG_FAMILIES = ("AFG", "AWG", "3320", "3321", "3322", "3325",
                 "3350", "3351", "3352", "3360", "3361", "3362")

# LXI mDNS service types instruments advertise.
_MDNS_SERVICES = ("_lxi._tcp.local.", "_scpi-raw._tcp.local.",
                  "_vxi-11._tcp.local.", "_hislip._tcp.local.")


# ---------------------------------------------------------------------------
# Identify a single host.
# ---------------------------------------------------------------------------
def probe_idn(ip: str, port: int, timeout: float = 1.0) -> str:
    """Open a socket, send *IDN?, and return the reply (empty string on any failure).

    The initial banner drain uses a SHORT timeout, not the full one: some instruments (the
    AFG especially) drop a freshly-opened socket if it sits idle, so we must send *IDN?
    promptly rather than block up to `timeout` waiting for a banner that may never come.
    """
    try:
        with socket.create_connection((ip, port), timeout=timeout) as s:
            s.settimeout(0.15)                     # brief drain - don't sit idle before *IDN?
            try:                                   # drain any connect banner / prompt
                s.recv(4096)
            except socket.timeout:
                pass
            s.settimeout(timeout)                  # now wait properly for the reply
            s.sendall(b"*IDN?\n")
            time.sleep(0.2)
            data = b""
            try:
                while True:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    data += chunk
            except socket.timeout:
                pass
            return data.decode(errors="replace")
    except OSError:
        return ""


def is_scope(idn: str) -> bool:
    """True if the *IDN? reply is a Tektronix or Keysight oscilloscope (not an AFG etc.)."""
    up = idn.upper()
    return (any(v in up for v in _INSTRUMENT_VENDORS)
            and any(fam in up for fam in _SCOPE_FAMILIES))


def is_function_generator(idn: str) -> bool:
    """True if the *IDN? reply is a Tektronix/Keysight function generator (AFG/AWG/33xxx)."""
    up = idn.upper()
    return (any(v in up for v in _INSTRUMENT_VENDORS)
            and any(fam in up for fam in _AFG_FAMILIES))


def device_kind(idn: str) -> str:
    """Classify an *IDN? reply: 'scope' | 'afg' | 'instrument' (known vendor, unknown role)
    | 'other' (no recognized vendor)."""
    if is_scope(idn):
        return "scope"
    if is_function_generator(idn):
        return "afg"
    if any(v in idn.upper() for v in _INSTRUMENT_VENDORS):
        return "instrument"
    return "other"


def _idn_model(idn: str) -> str:
    """'TEKTRONIX,MSO44,C012345,...' -> 'MSO44'."""
    parts = [p.strip() for p in idn.split(",")]
    return parts[1] if len(parts) > 1 else idn.strip()


def confirm(ip: str, ports: tuple[int, ...] = DEFAULT_PORTS,
            timeout: float = 1.0, retries: int = 1) -> dict | None:
    """Try each port on `ip`; return {ip, port, idn, model, kind} for the first that
    identifies as a known instrument (any supported vendor - scope OR function generator),
    else None.

    An instrument occasionally does not answer a fast *IDN? probe in time (returns empty),
    which would drop it from discovery. So when a port's socket opens but the reply is empty,
    we retry a couple of times (with a slightly longer timeout) before giving up on it - a
    reachable-but-silent host is exactly the case worth retrying.
    """
    for port in ports:
        for attempt in range(retries + 1):
            idn = probe_idn(ip, port, timeout * (1 + attempt))   # lengthen the wait each retry
            up = idn.upper()
            if any(v in up for v in _INSTRUMENT_VENDORS):
                # Keep the meaningful line (Terminal mode may echo the command / add a prompt).
                line = next((ln.strip(" \t\r\n>") for ln in idn.replace("\r", "\n").split("\n")
                             if any(v in ln.upper() for v in _INSTRUMENT_VENDORS)), idn.strip())
                return {"ip": ip, "port": port, "idn": line,
                        "model": _idn_model(line), "kind": device_kind(line)}
            if idn.strip():
                break            # got a non-empty reply that is not an instrument - move on
    return None


# ---------------------------------------------------------------------------
# Discovery: mDNS (primary) and subnet scan (fallback / alternative).
# ---------------------------------------------------------------------------
def discover_mdns_ips(timeout: float = 4.0,
                      service_types: tuple[str, ...] = _MDNS_SERVICES) -> set[str]:
    """Browse the LXI mDNS services for `timeout` seconds; return the set of IPv4 hosts
    that answered. Requires the 'zeroconf' package."""
    try:
        from zeroconf import Zeroconf, ServiceBrowser, ServiceListener
    except ImportError as exc:
        raise RuntimeError(
            "mDNS discovery needs the 'zeroconf' package. Install it with:\n"
            "    pip install zeroconf\n"
            "or use the subnet scan instead (scan_subnet / --subnet)."
        ) from exc

    ips: set[str] = set()

    class _Listener(ServiceListener):
        def add_service(self, zc, type_, name):
            info = zc.get_service_info(type_, name, timeout=2000)
            if info:
                for addr in info.parsed_addresses():
                    if ":" not in addr:            # IPv4 only
                        ips.add(addr)

        def update_service(self, zc, type_, name):
            self.add_service(zc, type_, name)

        def remove_service(self, zc, type_, name):
            pass

    zc = Zeroconf()
    listener = _Listener()
    browsers = [ServiceBrowser(zc, st, listener) for st in service_types]
    try:
        time.sleep(timeout)                        # let responses arrive
    finally:
        for b in browsers:
            b.cancel()
        zc.close()
    return ips


def scan_subnet(subnet: str, ports: tuple[int, ...] = DEFAULT_PORTS,
                timeout: float = 0.5, workers: int = 64) -> list[dict]:
    """Scan every host in `subnet` (e.g. '192.168.1.0/24') in parallel; return the
    confirmed Tektronix instruments as {ip, port, idn, model} dicts."""
    import ipaddress
    from concurrent.futures import ThreadPoolExecutor

    hosts = [str(ip) for ip in ipaddress.ip_network(subnet, strict=False).hosts()]
    found: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(lambda ip: confirm(ip, ports, timeout), hosts):
            if result:
                found.append(result)
    return found


def local_ipv4s() -> set[str]:
    """The machine's own IPv4 addresses (non-loopback), used to find which subnet(s) to
    scan. Pure stdlib - no traffic is actually sent."""
    ips: set[str] = set()
    try:                                          # primary interface toward the LAN
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))                # no packets sent for UDP connect()
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:                                          # any other interfaces (e.g. the bench NIC)
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return {ip for ip in ips if not ip.startswith("127.")}


def local_subnets(prefix: int = 24) -> list[str]:
    """The /prefix subnet(s) the machine is on, e.g. ['192.168.1.0/24'] - the address
    range we scan to find scopes."""
    import ipaddress
    return sorted({str(ipaddress.ip_network(f"{ip}/{prefix}", strict=False))
                   for ip in local_ipv4s()})


def neighbor_ips() -> set[str]:
    """IPv4 hosts the OS has already seen on the wire (its ARP/neighbor table).

    This is the fast, reliable way to find instruments on a LINK-LOCAL (169.254.0.0/16)
    bench: each device self-assigns a random address across the whole /16, so a /24 scan
    almost always misses them - but any device that has exchanged a packet shows up here.
    We then *IDN?-probe these candidates. Self IPs, multicast and broadcast are dropped.
    """
    import re
    import subprocess
    try:
        out = subprocess.run(["arp", "-a"], capture_output=True, text=True,
                             timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    mine = local_ipv4s()
    ips: set[str] = set()
    for ip in re.findall(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", out):
        if (ip in mine or ip.endswith(".255")
                or ip.startswith(("0.", "127.", "224.", "239.", "255."))
                or ip == "169.254.169.254"):        # APIPA metadata pseudo-address
            continue
        ips.add(ip)
    return ips


# A small on-disk cache of IPs where instruments were last found. On a link-local (/16)
# bench, ARP entries expire and devices sit on a different /24 than the PC, so neither the
# neighbor table nor a /24 scan reliably finds them on a later run. Re-probing the last-known
# IPs is fast and robust as long as the addresses are stable (they usually are).
_IP_CACHE_FILE = os.path.join(_HERE, ".instrument_ips.json")


def _load_cached_ips() -> set[str]:
    try:
        import json
        with open(_IP_CACHE_FILE, encoding="utf-8") as fh:
            return {str(ip) for ip in json.load(fh)}
    except (OSError, ValueError):
        return set()


def _save_cached_ips(ips: set[str]) -> None:
    try:
        import json
        with open(_IP_CACHE_FILE, "w", encoding="utf-8") as fh:
            json.dump(sorted(ips), fh)
    except OSError:
        pass


def discover_instruments(port: int | None = None, subnet: str | None = None,
                         timeout: float = 0.5, ports: tuple[int, ...] = DEFAULT_PORTS,
                         kinds: tuple[str, ...] | None = None,
                         use_neighbors: bool = True) -> list[dict]:
    """Find ALL supported instruments (scopes AND function generators) by *IDN?-probing hosts.
    This is the "detect IPs, ping with *IDN?, keep the responders" approach - it just doesn't
    throw away the non-scopes. Two sources of candidate IPs, unioned:
      1. a subnet scan (good for a normal /24 with static or DHCP addresses), and
      2. the OS ARP/neighbor table (essential on a LINK-LOCAL /16 bench, where each device
         self-assigns a random 169.254.x.x and a /24 scan would miss it).

    port    : the single SCPI port to probe. None = try the defaults (4000 and 5025).
    subnet  : a CIDR like "192.168.1.0/24" to scan. None = auto-detect the local subnet(s).
    kinds   : optional filter, e.g. ("scope",) or ("scope", "afg"). None = keep everything.
    use_neighbors : also probe IPs already in the ARP/neighbor table (recommended).
    Returns a list of {ip, port, idn, model, kind} dicts, one per instrument found.
    """
    from concurrent.futures import ThreadPoolExecutor

    probe_ports = (int(port),) if port else tuple(ports)
    subnets = [subnet] if subnet else local_subnets()
    results: list[dict] = []
    seen: set[str] = set()
    for sn in subnets:
        for info in scan_subnet(sn, probe_ports, timeout):
            if info["ip"] not in seen:
                results.append(info)
                seen.add(info["ip"])

    if use_neighbors:
        # Probe the ARP/neighbor table AND the last-known cached IPs. The cache covers the case
        # where an instrument's ARP entry has expired but its address is unchanged - common on a
        # link-local bench, and exactly why an earlier run finds a device the next one misses.
        extra = [ip for ip in (neighbor_ips() | _load_cached_ips()) if ip not in seen]
        if extra:
            with ThreadPoolExecutor(max_workers=min(64, len(extra))) as pool:
                for info in pool.map(lambda ip: confirm(ip, probe_ports, timeout), extra):
                    if info and info["ip"] not in seen:
                        results.append(info)
                        seen.add(info["ip"])

    if results:                                   # remember where instruments answered
        _save_cached_ips({r["ip"] for r in results})

    if kinds:
        keep = set(kinds)
        results = [r for r in results if r.get("kind") in keep]
    return results


def discover_scopes(port: int | None = None, subnet: str | None = None,
                    scopes_only: bool = True, timeout: float = 0.5,
                    ports: tuple[int, ...] = DEFAULT_PORTS) -> list[dict]:
    """Find scopes by scanning the network and *IDN?-probing every host. A thin filter over
    discover_instruments() kept for backward compatibility.

    scopes_only=True keeps only oscilloscopes; False keeps every identified instrument.
    Returns a list of {ip, port, idn, model, kind} dicts.
    """
    kinds = ("scope",) if scopes_only else None
    return discover_instruments(port=port, subnet=subnet, timeout=timeout,
                                ports=ports, kinds=kinds)


# ---------------------------------------------------------------------------
# A fleet of scope sessions.
# ---------------------------------------------------------------------------
class ScopeFleet:
    """Open and drive SocketScope sessions to several scopes at once, by alias."""

    def __init__(self) -> None:
        self.scopes: dict[str, bs.SocketScope] = {}

    def add(self, alias: str, host: str, port: int = 4000) -> str:
        """Open a session and return its *IDN?."""
        sc = bs.SocketScope(host, port)
        self.scopes[alias] = sc
        return sc.query("*IDN?").strip()

    @classmethod
    def from_discovery(cls, found: list[dict]) -> "ScopeFleet":
        """Build a fleet from discover_scopes() output. Aliases are the model + last IP
        octet, e.g. 'MSO44_134', so they are stable and human-readable."""
        fleet = cls()
        for info in found:
            alias = f"{info['model']}_{info['ip'].split('.')[-1]}"
            fleet.scopes[alias] = bs.SocketScope(info["ip"], info["port"])
        return fleet

    def identify_all(self) -> dict[str, str]:
        return {alias: sc.query("*IDN?").strip() for alias, sc in self.scopes.items()}

    def configure_all(self, setup_name: str,
                      channels: list[int] | None = None) -> dict[str, bool]:
        """Apply a named setup to every scope; return {alias: all_verified}."""
        setup = bs.SETUPS.get(setup_name)
        if setup is None:
            raise ValueError(f"Unknown setup {setup_name!r}. Available: {', '.join(bs.SETUPS)}")
        out: dict[str, bool] = {}
        for alias, sc in self.scopes.items():
            results = bs.verify(sc, bs.configure(sc, setup, channels))
            out[alias] = all(r.ok for r in results)
        return out

    def capture_all(self, channels: list[int],
                    points: int = 10000) -> dict[str, dict]:
        """Read the given channels off every scope; return {alias: {ch: Waveform}}."""
        return {alias: bs.acquire_many(sc, channels, points)
                for alias, sc in self.scopes.items()}

    def close_all(self) -> None:
        for sc in self.scopes.values():
            try:
                sc.close()
            except Exception:
                pass
        self.scopes.clear()


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------
def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Find Tektronix scopes by scanning the LAN and *IDN?-probing hosts.")
    ap.add_argument("--subnet", default=None, metavar="CIDR",
                    help="Scan this subnet, e.g. 192.168.1.0/24. Default: auto-detect the "
                         "local subnet(s).")
    ap.add_argument("--port", type=int, default=None,
                    help="SCPI port to probe (you determine this). Default: try 4000 and 5025.")
    ap.add_argument("--timeout", type=float, default=0.5,
                    help="Per-host connect timeout in seconds. Default 0.5.")
    ap.add_argument("--all", action="store_true",
                    help="Keep every identified instrument (function generators too), "
                         "not just oscilloscopes.")
    ap.add_argument("--open", action="store_true",
                    help="Open a session to every discovered scope and print each *IDN?.")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    targets = args.subnet or ", ".join(local_subnets()) or "(no local subnet found)"
    port_note = args.port if args.port else f"{DEFAULT_PORTS}"
    print(f"Scanning {targets} on port {port_note} with *IDN? ...")
    found = discover_scopes(port=args.port, subnet=args.subnet,
                            scopes_only=not args.all, timeout=args.timeout)

    if not found:
        print("No scopes found.", file=sys.stderr)
        return 1

    print(f"\nFound {len(found)} instrument(s):")
    for f in found:
        print(f"  {f['ip']}:{f['port']}  [{f.get('kind', '?')}]  {f['idn']}")

    if args.open:
        fleet = ScopeFleet.from_discovery(found)
        try:
            print("\nOpened sessions:")
            for alias, idn in fleet.identify_all().items():
                print(f"  [{alias}] {idn}")
        finally:
            fleet.close_all()
    return 0


if __name__ == "__main__":
    sys.exit(main())
