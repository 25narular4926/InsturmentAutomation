#!/usr/bin/env python3
"""TestStand-facing API for driving a whole bench of instruments at once (by alias).

The multi-instrument twin of teststand_api.py. Where teststand_api holds ONE scope session,
this holds several, each identified by an alias string. Discovery classifies every *IDN?
responder: oscilloscopes are driven with bench_socket (get_*/capture/save_* below), and
function generators are driven with the function_generator library (the afg_* functions).
One scan detects the whole bench and opens the right driver for each device.

Every function takes an alias as its first argument and takes/returns ONLY primitive types
(str / int / float / bool / list), so a TestStand sequence can loop over devices or address
them by name and bind results straight to sequence variables.

You choose the port. Pass 0 to probe both 4000 (Tek Socket Server) and 5025 (Keysight LXI),
which is what you want when a Keysight instrument shares the bench with Tektronix gear.

Typical use (scopes + a function generator, discovered together):
    aliases = connect_discovered(0)             # ["MSO44_134", "AFG31102_71", ...]
    afg_configure("AFG31102_71", "sine_1k", "1")
    afg_output_on("AFG31102_71", 1)             # drive the stimulus
    for a in aliases:
        if is_scope_alias(a):
            configure(a, "bench_full", "1,2")
            capture(a, "1,2")
            vmax = get_vmax(a, 1)               # <- limits per scope
            save_png(a, "C:\\\\results\\\\" + a + ".png")
    afg_all_off_everywhere()                     # leave the bench quiet
    disconnect_all()
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# The function-generator library lives in a sibling folder (../function_generator).
# Discovery may turn up an AFG alongside the scopes, and when it does we drive it with
# THAT library - the same way the scopes are driven with bench_socket.
_AFG_DIR = os.path.join(os.path.dirname(_HERE), "function_generator")
if _AFG_DIR not in sys.path:
    sys.path.insert(0, _AFG_DIR)

import bench_socket as bs   # noqa: E402
import discovery            # noqa: E402
import afg_socket as afg    # noqa: E402  (the function-generator library, from ../function_generator)

# ---------------------------------------------------------------------------
# Session state - keyed by alias. Scopes and function generators live in separate
# dicts but share one alias namespace, so a discovered bench of both is addressed
# uniformly by name.
# ---------------------------------------------------------------------------
_scopes: dict[str, bs.SocketScope] = {}
_afgs: dict[str, afg.SocketAFG] = {}
_waves: dict[str, dict[int, bs.Waveform]] = {}
_reports: dict[str, str] = {}
_afg_reports: dict[str, str] = {}
_record_length: dict[str, int] = {}
_last_found: list[dict] = []       # cache of the last scan, so connect_matching can reuse it


def _serial(idn: str) -> str:
    """'TEKTRONIX,MSO44,C012345,FV:2.0' -> 'C012345' (the serial number field)."""
    parts = [p.strip() for p in idn.split(",")]
    return parts[2] if len(parts) > 2 else ""


def _require_scope(alias: str) -> bs.SocketScope:
    if alias not in _scopes:
        raise RuntimeError(
            f"No scope connected as {alias!r}. Connected scopes: {list_scopes() or 'none'}."
        )
    return _scopes[alias]


def _require_afg(alias: str) -> afg.SocketAFG:
    if alias not in _afgs:
        raise RuntimeError(
            f"No function generator connected as {alias!r}. "
            f"Connected generators: {list_generators() or 'none'}."
        )
    return _afgs[alias]


def _open_device(alias: str, info: dict) -> None:
    """Open the right driver for a discovered device: a function generator gets a SocketAFG
    (the function_generator library), everything else gets a SocketScope. Connects on the
    port the device actually answered *IDN? on, so a mixed 4000/5025 bench works."""
    disconnect_device(alias)                      # drop any stale session under this alias
    port = int(info.get("port") or 4000)
    if info.get("kind") == "afg":
        _afgs[alias] = afg.SocketAFG(info["ip"], port)
    else:
        _scopes[alias] = bs.SocketScope(info["ip"], port)


def _identify_any(alias: str) -> str:
    """*IDN? of whatever is connected under this alias (scope or generator)."""
    if alias in _scopes:
        return _scopes[alias].query("*IDN?")
    if alias in _afgs:
        return _afgs[alias].query("*IDN?")
    return ""


def _require_wave(alias: str, channel: int) -> bs.Waveform:
    waves = _waves.get(alias, {})
    if channel not in waves:
        raise RuntimeError(
            f"No captured data for {alias!r} CH{channel}. Call capture() first "
            f"(captured: {sorted(waves) or 'none'})."
        )
    return waves[channel]


def _parse_channels(channels: str) -> list[int]:
    return [int(c) for c in str(channels).split(",") if c.strip()]


# ---------------------------------------------------------------------------
# Connection (you choose the port).
# ---------------------------------------------------------------------------
def connect_scope(alias: str, host: str, port: int = 4000) -> str:
    """Open a session to one scope under `alias`. Returns its *IDN?.

    You pick the port (default 4000). Raises if the scope cannot be reached.
    """
    disconnect_device(alias)                     # drop any stale session with this alias
    try:
        _scopes[alias] = bs.SocketScope(host, int(port))
    except OSError as exc:
        raise RuntimeError(
            f"Cannot reach {alias!r} at {host}:{port} - {exc}. "
            f"Is the Socket Server ON on that port?"
        ) from exc
    return _scopes[alias].query("*IDN?")


def connect_generator(alias: str, host: str, port: int = 4000) -> str:
    """Open a session to one function generator under `alias`, driven by the
    function_generator library. Returns its *IDN?. The AFG twin of connect_scope().

    You pick the port (default 4000 for the Tektronix Socket Server). Raises if unreachable.
    """
    disconnect_device(alias)                     # drop any stale session with this alias
    try:
        _afgs[alias] = afg.SocketAFG(host, int(port))
    except OSError as exc:
        raise RuntimeError(
            f"Cannot reach generator {alias!r} at {host}:{port} - {exc}. "
            f"Is the Socket Server ON (Terminal mode) on that port?"
        ) from exc
    return _afgs[alias].query("*IDN?")


def _probe_port(port: int) -> int | None:
    """Turn a TestStand port argument into a discovery probe port. port <= 0 means "try the
    defaults (4000 and 5025)" so a mixed Tek(4000)/Keysight(5025) bench is found in one scan."""
    return int(port) if int(port) > 0 else None


def connect_discovered(port: int = 4000, subnet: str = "", timeout: float = 0.5) -> list[str]:
    """Scan the network, *IDN?-probe every host, and open a session to each instrument found -
    a SocketScope for every oscilloscope AND a SocketAFG (function-generator library) for every
    function generator. One flow detects and connects the whole bench.

    This is the "detect the available IPs, ping each with *IDN?, and whoever answers becomes a
    device" flow. If several answer, several sessions open - one per device, each with the
    driver its *IDN? calls for.

    port    : the SCPI port to probe and connect on. Pass 0 to try both 4000 and 5025 (needed
              to catch a Keysight instrument on 5025 alongside Tektronix gear on 4000).
    subnet  : "" -> auto-detect the local subnet(s). A CIDR like "192.168.1.0/24" -> scan it.
    timeout : per-host connect timeout in seconds.

    Returns the list of aliases created (model + last IP octet, e.g. "MSO44_134", "AFG31102_71").
    Use is_generator(alias)/is_scope_alias(alias) to tell which is which.
    """
    global _last_found
    _last_found = discovery.discover_instruments(port=_probe_port(port), subnet=subnet or None,
                                                 timeout=timeout, kinds=("scope", "afg"))
    aliases: list[str] = []
    for info in _last_found:
        alias = f"{info['model']}_{info['ip'].split('.')[-1]}"
        _open_device(alias, info)
        aliases.append(alias)
    return aliases


def scan(port: int = 4000, subnet: str = "", timeout: float = 0.5) -> list[str]:
    """Discover instruments WITHOUT connecting, and return a readable line per device so you can
    see each one's kind and serial (to build your alias mapping). Also caches the result so a
    following connect_matching()/connect_discovered_as() reuses it instead of re-scanning.

        ['scope  MSO44  serial=C012345  192.168.1.10:4000',
         'afg    AFG31102  serial=C023456  192.168.1.11:4000']
    """
    global _last_found
    _last_found = discovery.discover_instruments(port=_probe_port(port), subnet=subnet or None,
                                                 timeout=timeout, kinds=("scope", "afg"))
    return [f"{i.get('kind', '?'):<6} {i['model']}  serial={_serial(i['idn'])}  "
            f"{i['ip']}:{i['port']}" for i in _last_found]


def connect_matching(alias: str, match: str, port: int = 4000, subnet: str = "",
                     timeout: float = 0.5) -> str:
    """Auto-discover, find the instrument whose *IDN? contains `match`, and open it under YOUR
    `alias` with the right driver (scope or function generator). This is connect_scope WITHOUT
    typing an IP - you identify the device by its serial (or model) instead. Call it once per
    device you care about.

    match : any substring of the target device's *IDN?, typically its serial number
            (printed on the instrument), e.g. "C012345".

    Reuses the last scan()/discovery if there is one, else scans now. Returns the connected
    device's *IDN?, or "" if nothing discovered matched.
    """
    found = _last_found or discovery.discover_instruments(
        port=_probe_port(port), subnet=subnet or None, timeout=timeout, kinds=("scope", "afg"))
    m = str(match).upper()
    for info in found:
        if m in info["idn"].upper():
            _open_device(alias, info)
            return _identify_any(alias)
    return ""


def connect_discovered_as(mapping: dict, port: int = 4000, subnet: str = "",
                          timeout: float = 0.5) -> list[str]:
    """Auto-discover once, then open each matched instrument under YOUR chosen alias with the
    right driver (scope or function generator).

    mapping : {match: alias}, where `match` is a substring of a device's *IDN? (its serial
              or model), e.g. {"C012345": "cranking", "AFG31102": "stimulus"}.

    Combines discovery (no IPs to type) with your own naming (so you can configure each
    differently by alias). Returns the aliases that matched and connected.
    """
    global _last_found
    _last_found = discovery.discover_instruments(port=_probe_port(port), subnet=subnet or None,
                                                 timeout=timeout, kinds=("scope", "afg"))
    connected: list[str] = []
    for info in _last_found:
        up = info["idn"].upper()
        for match, alias in mapping.items():
            if str(match).upper() in up:
                _open_device(alias, info)
                connected.append(alias)
                break
    return connected


def disconnect_scope(alias: str) -> bool:
    """Close one scope's session (and drop its captured data). Safe if not connected."""
    sc = _scopes.pop(alias, None)
    if sc is not None:
        try:
            sc.close()
        except Exception:
            pass
    _waves.pop(alias, None)
    _reports.pop(alias, None)
    _record_length.pop(alias, None)
    return True


def disconnect_generator(alias: str) -> bool:
    """Close one function generator's session. Safe if not connected.

    NOTE: this does NOT switch its outputs off - call afg_all_off(alias) first if you want
    the bench left quiet.
    """
    gen = _afgs.pop(alias, None)
    if gen is not None:
        try:
            gen.close()
        except Exception:
            pass
    _afg_reports.pop(alias, None)
    return True


def disconnect_device(alias: str) -> bool:
    """Close whatever is connected under this alias, scope or generator. Safe if not connected."""
    disconnect_scope(alias)
    disconnect_generator(alias)
    return True


def disconnect_all() -> bool:
    """Close every session (scopes and generators). The safe way to end the sequence."""
    for alias in list(_scopes):
        disconnect_scope(alias)
    for alias in list(_afgs):
        disconnect_generator(alias)
    return True


def list_scopes() -> list[str]:
    """Aliases of every currently-connected scope."""
    return sorted(_scopes)


def list_generators() -> list[str]:
    """Aliases of every currently-connected function generator."""
    return sorted(_afgs)


def list_devices() -> list[str]:
    """Aliases of every connected instrument (scopes and generators)."""
    return sorted(set(_scopes) | set(_afgs))


def is_connected(alias: str) -> bool:
    """True if any instrument (scope or generator) is connected under this alias."""
    return alias in _scopes or alias in _afgs


def is_scope_alias(alias: str) -> bool:
    """True if the alias is a connected oscilloscope."""
    return alias in _scopes


def is_generator(alias: str) -> bool:
    """True if the alias is a connected function generator."""
    return alias in _afgs


def identify(alias: str) -> str:
    """The instrument's *IDN? string (scope or generator)."""
    idn = _identify_any(alias)
    if not idn:
        raise RuntimeError(
            f"Nothing connected as {alias!r}. Connected: {list_devices() or 'none'}."
        )
    return idn


# ---------------------------------------------------------------------------
# Configure / capture (per alias).
# ---------------------------------------------------------------------------
def list_setups() -> list[str]:
    """Names of the available named setups (shared by all scopes)."""
    return list(bs.SETUPS)


def configure(alias: str, setup_name: str = "bench_full", channels: str = "",
              duration_s: float = 0.0, horizontal_scale: float = 0.0) -> bool:
    """Apply a named setup to one scope and verify every setting read back.

    Same behaviour as the single-scope configure(), but for the scope named `alias`.
    horizontal_scale (seconds/div, >0) overrides the setup's timebase to set the window width.
    """
    scope = _require_scope(alias)
    setup = bs.SETUPS.get(setup_name)
    if setup is None:
        raise ValueError(f"Unknown setup {setup_name!r}. Available: {', '.join(bs.SETUPS)}")

    chans = _parse_channels(channels) or sorted(setup.channels) or [1]
    dur = float(duration_s) if duration_s and duration_s > 0 else None
    hs = float(horizontal_scale) if horizontal_scale and horizontal_scale > 0 else None
    applied = bs.configure(scope, setup, chans, duration=dur, horizontal_scale=hs)
    results = bs.verify(scope, applied)

    _record_length[alias] = 0
    for s in applied:
        lab = s.label.upper()
        if "RECO" in lab or "POIN" in lab:      # Tek HORizontal:RECOrdlength / Keysight :ACQuire:POINts
            try:
                _record_length[alias] = int(float(s.expected))
            except (TypeError, ValueError):
                _record_length[alias] = 0

    passed = sum(1 for r in results if r.ok)
    lines = [f"[{alias}] setup '{setup.name}' -> " + ", ".join(f"CH{c}" for c in chans), ""]
    width = max((len(r.label) for r in results), default=0)
    for r in results:
        mark = "PASS" if r.ok else "FAIL"
        lines.append(f"[{mark}] {r.label:<{width}}  set {r.expected}  readback {r.readback}")
    lines.append("")
    lines.append(f"{passed}/{len(results)} settings verified")
    _reports[alias] = "\n".join(lines)
    return passed == len(results)


def get_config_report(alias: str) -> str:
    """The PASS/FAIL table from the last configure() on this scope."""
    return _reports.get(alias, "")


def capture(alias: str, channels: str = "1", points: int = 0, single: bool = False,
            timeout_s: float = 120.0) -> bool:
    """Capture one scope's channels into memory for its get_*/save_* calls.

    single=False (default) forces a fresh, frozen record via AUTO self-trigger and reads it -
    vendor-aware, so it works on both Tektronix and Keysight even when the configured trigger
    would never fire. single=True instead arms ONE real acquisition and waits for the trigger
    (Tektronix). points=0 uses the record length that scope's configure set.
    """
    scope = _require_scope(alias)
    chans = _parse_channels(channels) or [1]
    n_points = int(points) if int(points) > 0 else (_record_length.get(alias, 0) or 1000)

    if single:
        if not bs.arm_single(scope, float(timeout_s)):
            raise TimeoutError(
                f"[{alias}] no trigger within {timeout_s:g} s. Check the trigger, and that "
                f"trigger mode is NORMal."
            )
        _waves[alias] = bs.acquire_many(scope, chans, n_points)
    else:
        _waves[alias] = bs.capture_live(scope, chans, n_points)
    return len(_waves[alias]) == len(chans)


def captured_channels(alias: str) -> list[int]:
    """Which channels returned data on this scope's last capture()."""
    return sorted(_waves.get(alias, {}))


# ---------------------------------------------------------------------------
# Measurements (per alias + channel). Same math as the single-scope API.
# ---------------------------------------------------------------------------
def get_vmax(alias: str, channel: int = 1) -> float:
    """Maximum volts."""
    return bs.measure_vmax(_require_wave(alias, int(channel)))


def get_vmin(alias: str, channel: int = 1) -> float:
    """Minimum volts."""
    return bs.measure_vmin(_require_wave(alias, int(channel)))


def get_mean(alias: str, channel: int = 1) -> float:
    """Mean (average) volts."""
    return bs.measure_mean(_require_wave(alias, int(channel)))


def get_rms(alias: str, channel: int = 1) -> float:
    """True RMS volts (any shape)."""
    return bs.measure_rms(_require_wave(alias, int(channel)))


def get_pulse_width(alias: str, channel: int = 1) -> float:
    """Positive pulse width in seconds (first pulse). 0.0 if flat / no complete pulse."""
    return bs.measure_pulse_width(_require_wave(alias, int(channel)))


def get_pulse_width_negative(alias: str, channel: int = 1) -> float:
    """Negative (low) pulse width in seconds (first pulse). 0.0 if flat / no complete pulse."""
    return bs.measure_pulse_width_negative(_require_wave(alias, int(channel)))


def get_sample_count(alias: str, channel: int = 1) -> int:
    """How many samples were transferred."""
    return int(len(_require_wave(alias, int(channel)).v))


def get_dt(alias: str, channel: int = 1) -> float:
    """Seconds between consecutive samples."""
    return float(_require_wave(alias, int(channel)).dt)


def get_t0(alias: str, channel: int = 1) -> float:
    """Time of the first sample (negative = before the trigger)."""
    return float(_require_wave(alias, int(channel)).t0)


def get_duration(alias: str, channel: int = 1) -> float:
    """Time from the first sample to the last, in seconds."""
    wf = _require_wave(alias, int(channel))
    return float(wf.t[-1] - wf.t[0])


# ---------------------------------------------------------------------------
# Saving (per alias). One channel -> the path; several -> per-channel + joint.
# ---------------------------------------------------------------------------
def _ensure_dir(path: str) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    if folder:
        os.makedirs(folder, exist_ok=True)


def save_csv(alias: str, path: str) -> str:
    """Save this scope's captured data as CSV. Returns the path(s) written."""
    waves = _waves.get(alias)
    if not waves:
        raise RuntimeError(f"Nothing captured for {alias!r}. Call capture() first.")
    _ensure_dir(path)
    written: list[str] = []
    multi = len(waves) > 1
    for c in sorted(waves):
        p = bs._derive(path, waves[c].channel) if multi else path
        bs.save_csv(waves[c], p)
        written.append(p)
    if multi:
        p = bs._derive(path, "joint")
        bs.save_joint_csv(waves, p)
        written.append(p)
    return ";".join(written)


def save_png(alias: str, path: str) -> str:
    """Save a PNG plot of this scope's captured data. Returns the path(s) written.

    The scope's alias is written into the plot TITLE so an opened PNG says which scope it
    came from (the filename is set by the caller / teststand_api's save_scope_png).
    """
    waves = _waves.get(alias)
    if not waves:
        raise RuntimeError(f"Nothing captured for {alias!r}. Call capture() first.")
    _ensure_dir(path)
    written: list[str] = []
    multi = len(waves) > 1
    for c in sorted(waves):
        p = bs._derive(path, waves[c].channel) if multi else path
        bs.save_png(waves[c], p, label=alias)
        written.append(p)
    if multi:
        p = bs._derive(path, "joint")
        bs.save_png_joint(waves, p, label=alias)
        written.append(p)
    return ";".join(written)


# ---------------------------------------------------------------------------
# Raw SCPI (per alias).
# ---------------------------------------------------------------------------
def query(alias: str, scpi: str) -> str:
    """Send a SCPI query to one scope and return the reply."""
    return _require_scope(alias).query(str(scpi))


def send(alias: str, scpi: str) -> bool:
    """Send a SCPI command to one scope (no reply). Always True."""
    _require_scope(alias).write(str(scpi))
    return True


# ===========================================================================
# FUNCTION GENERATORS (per alias). When discovery turns up an AFG, it is driven
# with the function_generator library through these afg_* functions - the generator
# twin of the scope functions above. Output control is EXPLICIT: configuring a waveform
# does NOT enable an output. You must call afg_output_on() deliberately, because it drives
# real hardware.
# ===========================================================================
def afg_list_setups() -> list[str]:
    """Names of the available AFG waveform setups (from ../function_generator/configs)."""
    return list(afg.SETUPS)


def afg_configure(alias: str, setup_name: str, channels: str = "") -> bool:
    """Apply a named AFG waveform setup to one generator and verify every setting read back.

    channels : "1" or "1,2" to force channels, "" to use the channels the setup defines.
    Applies waveform parameters ONLY - does NOT switch any output on. Returns True only if
    every setting read back correctly.
    """
    gen = _require_afg(alias)
    setup = afg.SETUPS.get(setup_name)
    if setup is None:
        raise ValueError(f"Unknown AFG setup {setup_name!r}. Available: {', '.join(afg.SETUPS)}")

    chans = _parse_channels(channels) or sorted(setup.channels) or [1]
    applied = afg.configure(gen, setup, chans)
    results = afg.verify(gen, applied)

    passed = sum(1 for r in results if r.ok)
    lines = [f"[{alias}] AFG setup '{setup.name}' -> " + ", ".join(f"CH{c}" for c in chans), ""]
    width = max((len(r.label) for r in results), default=0)
    for r in results:
        mark = "PASS" if r.ok else "FAIL"
        lines.append(f"[{mark}] {r.label:<{width}}  set {r.expected}  readback {r.readback}")
    lines.append("")
    lines.append(f"{passed}/{len(results)} settings verified")
    _afg_reports[alias] = "\n".join(lines)
    return passed == len(results)


def afg_set_waveform(alias: str, channel: int = 1, shape: str = "SIN",
                     frequency: float = 1000.0, amplitude: float = 1.0,
                     offset: float = 0.0, duty_cycle: float = 0.0) -> bool:
    """Set one generator channel's waveform directly (no named setup) and verify it.

    Pass the numbers in as TestStand step parameters. Does NOT switch the output on.
    duty_cycle is only sent when > 0 (pulse/square). Returns True only if every setting
    read back correctly.
    """
    gen = _require_afg(alias)
    cw = afg.ChannelWaveform(
        shape=str(shape), frequency=float(frequency), amplitude=float(amplitude),
        offset=float(offset),
        duty_cycle=float(duty_cycle) if duty_cycle and duty_cycle > 0 else None,
    )
    setup = afg.WaveformSetup(name="direct", channels={int(channel): cw})
    applied = afg.configure(gen, setup, [int(channel)])
    results = afg.verify(gen, applied)

    passed = sum(1 for r in results if r.ok)
    lines = [f"[{alias}] CH{channel} waveform set directly", ""]
    width = max((len(r.label) for r in results), default=0)
    for r in results:
        mark = "PASS" if r.ok else "FAIL"
        lines.append(f"[{mark}] {r.label:<{width}}  set {r.expected}  readback {r.readback}")
    _afg_reports[alias] = "\n".join(lines)
    return passed == len(results)


def afg_get_config_report(alias: str) -> str:
    """The PASS/FAIL table from the last afg_configure()/afg_set_waveform() on this generator."""
    return _afg_reports.get(alias, "")


def afg_output_on(alias: str, channel: int = 1) -> bool:
    """Switch a generator channel's output ON. This drives real hardware - call it deliberately."""
    afg.output_on(_require_afg(alias), int(channel))
    return True


def afg_output_off(alias: str, channel: int = 1) -> bool:
    """Switch a generator channel's output OFF."""
    afg.output_off(_require_afg(alias), int(channel))
    return True


def afg_all_off(alias: str) -> bool:
    """Switch every output OFF on one generator - the safe way to leave the bench in Cleanup."""
    afg.all_outputs_off(_require_afg(alias))
    return True


def afg_all_off_everywhere() -> bool:
    """Switch every output OFF on every connected generator. Safe blanket Cleanup."""
    for alias in list(_afgs):
        try:
            afg.all_outputs_off(_afgs[alias])
        except Exception:
            pass
    return True


def afg_output_is_on(alias: str, channel: int = 1) -> bool:
    """True if the generator channel's output is currently ON."""
    return afg.output_state(_require_afg(alias), int(channel))


def afg_query(alias: str, scpi: str) -> str:
    """Send a SCPI query to one generator and return the reply."""
    return _require_afg(alias).query(str(scpi))


def afg_send(alias: str, scpi: str) -> bool:
    """Send a SCPI command to one generator (no reply). Always True."""
    _require_afg(alias).write(str(scpi))
    return True
