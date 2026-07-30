#!/usr/bin/env python3
"""Drive a Tektronix AFG31102 function generator over its raw Socket Server (LAN).

This is the function-generator twin of the oscilloscope's bench_socket.py, and it is
built the same way on purpose:
  - a thin socket transport (SocketAFG) that speaks SCPI over TCP, no VISA, no drivers;
  - named waveform setups loaded from editable JSON files in the configs/ folder;
  - configure() applies a setup and reads every setting back (PASS/FAIL);
  - output on/off is EXPLICIT and separate - it is never a side effect of configure().

Nothing here turns an output ON by itself. Setting up a waveform and switching the
output on are deliberately two different calls, because the output drives real hardware.

Key AFG31102 SCPI (reference - confirm against the live bench):
  SOURce<n>:FUNCtion:SHAPe  SIN | SQUare | RAMP | PULSe | ...
  SOURce<n>:FREQuency       <hz>
  SOURce<n>:VOLTage:AMPLitude <vpp>
  SOURce<n>:VOLTage:OFFSet  <v>
  SOURce<n>:PULSe:DCYCle    <percent>        (pulse duty cycle)
  SOURce<n>:PHASe:ADJust    <deg>
  OUTPut<n>:IMPedance       <ohms> | INFinity
  OUTPut<n>:STATE           ON | OFF

Usage:
  python afg_socket.py --host 169.254.8.135 --identify
  python afg_socket.py --host 169.254.8.135 --list-setups
  python afg_socket.py --host 169.254.8.135 --configure --setup sine_1k
  python afg_socket.py --host 169.254.8.135 --output-on --channel 1
  python afg_socket.py --host 169.254.8.135 --all-off
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import time
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Transport - the same raw-socket SCPI client the scope library uses.
# ---------------------------------------------------------------------------
class SocketAFG:
    """Minimal raw-socket SCPI client for a Tektronix AFG over its SCPI socket.

    Works on the port-4000 Socket Server (Terminal mode, which echoes) and on the raw LXI
    SCPI port 5025 (no echo). The AFG drops idle raw-socket connections, so every write/query
    transparently reconnects and retries once if the socket has been closed underneath us -
    which is what happens when an instrument sits idle between TestStand steps.
    """

    def __init__(self, host: str, port: int = 4000, timeout: float = 5.0) -> None:
        self.host = host
        self.port = int(port)
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self._last_io = 0.0
        self._connect()

    # Per-read timeout used to detect "reply done" (a short silence ends a reply). Small on
    # purpose: on a raw 5025 socket replies arrive in one burst, so a bigger value just wastes
    # a full timeout on every query/write.
    READ_TIMEOUT = 0.4
    DRAIN_TIMEOUT = 0.12           # after a write there is only fast echo (or none)
    # If the socket has been idle longer than this, reconnect BEFORE sending. The AFG silently
    # drops idle connections, and a send on a half-open socket can succeed (data lost) without
    # raising - proactive reconnect on idle avoids that race (e.g. while a scope is configured).
    IDLE_RECONNECT = 5.0

    def _connect(self) -> None:
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.READ_TIMEOUT)
        self._drain()                  # discard any connect-time banner / prompt
        # Bare query responses: HEADer OFF strips the ":SOURCE1:FREQUENCY " prefix so
        # replies are plain values that float() can parse. VERBose OFF keeps them terse.
        # Sent raw (not via write()) so a failure here can't recurse into a reconnect.
        for setup in (b"HEADer OFF\n", b"VERBose OFF\n"):
            self.sock.sendall(setup)
            time.sleep(0.1)
            self._drain()
        self._last_io = time.monotonic()

    def _reconnect(self) -> None:
        """Re-open the socket after the AFG dropped an idle connection."""
        try:
            if self.sock is not None:
                self.sock.close()
        except OSError:
            pass
        self._connect()

    def _ensure_fresh(self) -> None:
        """Reconnect proactively if the socket has been idle long enough that the AFG may have
        dropped it - so we never send on a half-open connection."""
        if time.monotonic() - self._last_io > self.IDLE_RECONNECT:
            self._reconnect()

    def _drain(self) -> None:
        self.sock.settimeout(self.DRAIN_TIMEOUT)
        try:
            while self.sock.recv(4096):
                pass
        except socket.timeout:
            pass
        finally:
            self.sock.settimeout(self.READ_TIMEOUT)

    def _read(self) -> str:
        chunks: list[bytes] = []
        try:
            while True:
                data = self.sock.recv(4096)
                if not data:
                    break
                chunks.append(data)
        except socket.timeout:
            pass
        return b"".join(chunks).decode(errors="replace")

    def query(self, cmd: str, *, debug: bool = False) -> str:
        self._ensure_fresh()
        try:
            self.sock.sendall(cmd.encode() + b"\n")
            time.sleep(0.2)
            raw = self._read()
        except OSError:                # idle connection dropped - reconnect and retry once
            self._reconnect()
            self.sock.sendall(cmd.encode() + b"\n")
            time.sleep(0.2)
            raw = self._read()
        self._last_io = time.monotonic()
        if debug:
            print(f"  raw reply: {raw!r}", file=sys.stderr)
        return _clean(raw, cmd)

    def write(self, cmd: str) -> None:
        self._ensure_fresh()
        try:
            self.sock.sendall(cmd.encode() + b"\n")
            time.sleep(0.1)
            self._drain()
        except OSError:                # idle connection dropped - reconnect and retry once
            self._reconnect()
            self.sock.sendall(cmd.encode() + b"\n")
            time.sleep(0.1)
            self._drain()
        self._last_io = time.monotonic()

    def close(self) -> None:
        if self.sock is not None:
            self.sock.close()


def _clean(raw: str, cmd: str) -> str:
    """Strip Terminal-mode echo and prompt noise; return the meaningful reply line."""
    lines = [ln.strip(" \t\r\n>") for ln in raw.replace("\r", "\n").split("\n")]
    lines = [ln for ln in lines if ln and ln != cmd.strip()]
    return lines[-1] if lines else ""


def _to_float(text: str) -> float:
    """Parse a numeric reply, tolerating a stray HEADer prefix like ':SOURCE1:FREQ 1E3'."""
    s = text.strip()
    try:
        return float(s.split()[-1]) if s else float(s)
    except ValueError:
        m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", s)
        if m:
            return float(m.group())
        raise ValueError(f"could not parse a number from AFG reply: {text!r}")


# ---------------------------------------------------------------------------
# Waveform setups - editable JSON files in the configs/ folder, one per setup.
#
# JSON schema (all fields optional; null or omitted = leave that setting alone):
#   {
#     "name": "sine_1k",
#     "default_channel": { "shape": "SIN", "frequency": 1000, "amplitude": 2.0,
#                          "offset": 0.0, "duty_cycle": null, "phase": null,
#                          "impedance": 50 },
#     "channels": { "1": { "shape": "SIN", "frequency": 1000, ... } }
#   }
# Any key starting with "_" (e.g. "_comment") is ignored, so annotate freely.
# NOTE: output state is deliberately NOT part of a setup - use output_on()/output_off().
# ---------------------------------------------------------------------------
@dataclass
class ChannelWaveform:
    """Per-channel waveform settings for one AFG output."""
    shape: str | None = None          # SIN | SQUare | RAMP | PULSe | ...
    frequency: float | None = None    # Hz
    amplitude: float | None = None    # Vpp
    offset: float | None = None       # volts
    duty_cycle: float | None = None   # percent. PULSe/SQUare: high-time duty. RAMP: rise
                                      # symmetry (50 = symmetric triangle, 100/0 = sawtooth).
    phase: float | None = None        # degrees
    impedance: float | None = None    # output load in ohms (50), or use "INF" for high-Z
    # Pulse-by-levels (an alternative to amplitude/offset for a PULSe shape):
    pulse_rate: float | None = None          # seconds (the pulse PERIOD, e.g. "2 s")
    pulse_width: float | None = None         # seconds (high time, e.g. "950 ms")
    pulse_high_voltage: float | None = None  # volts
    pulse_low_voltage: float | None = None   # volts


@dataclass
class WaveformSetup:
    name: str = "custom"
    channels: dict[int, ChannelWaveform] = field(default_factory=dict)
    default_channel: ChannelWaveform = field(default_factory=ChannelWaveform)


CONFIGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "configs")

_CHANNEL_FIELDS = ("shape", "frequency", "amplitude", "offset", "duty_cycle",
                   "phase", "impedance", "pulse_rate", "pulse_width",
                   "pulse_high_voltage", "pulse_low_voltage")

# How each field's value is interpreted when it carries a unit string.
_AFG_KINDS = {"frequency": "freq", "amplitude": "voltage", "offset": "voltage",
              "duty_cycle": "number", "phase": "number", "impedance": "ohm",
              "pulse_rate": "time", "pulse_width": "time",
              "pulse_high_voltage": "voltage", "pulse_low_voltage": "voltage"}


def _parse_value(value: Any, kind: str | None):
    """Coerce a config value to a plain number in the AFG's native units (frequency in Hz,
    amplitude in Vpp, pulse_rate/width in seconds, voltages in V). shape stays a string."""
    if value is None:
        return value
    if kind == "ohm":
        if isinstance(value, str) and "inf" in value.lower():
            return "INFinity"
        return float(value)
    return float(value)


def _channel_from_dict(d: dict) -> ChannelWaveform:
    out: dict[str, Any] = {}
    for key, val in d.items():
        if key in _CHANNEL_FIELDS and val is not None:
            out[key] = val if key == "shape" else _parse_value(val, _AFG_KINDS.get(key))
    return ChannelWaveform(**out)


def _setup_from_dict(data: dict, fallback_name: str) -> WaveformSetup:
    channels = {int(n): _channel_from_dict(cw)
                for n, cw in (data.get("channels") or {}).items()}
    default_channel = _channel_from_dict(data.get("default_channel") or {})
    return WaveformSetup(name=data.get("name") or fallback_name,
                         channels=channels, default_channel=default_channel)


def load_setups(configs_dir: str = CONFIGS_DIR) -> dict[str, WaveformSetup]:
    """Load every configs/<name>.json into a {name: WaveformSetup} dict."""
    setups: dict[str, WaveformSetup] = {}
    if not os.path.isdir(configs_dir):
        print(f"WARNING: configs folder not found: {configs_dir}\n"
              f"         No named setups loaded. Create it with <name>.json files.",
              file=sys.stderr)
        return setups
    for fn in sorted(os.listdir(configs_dir)):
        if not fn.lower().endswith(".json"):
            continue
        path = os.path.join(configs_dir, fn)
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            setup = _setup_from_dict(data, os.path.splitext(fn)[0])
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            print(f"WARNING: skipping bad config {fn}: {exc}", file=sys.stderr)
            continue
        setups[setup.name] = setup
    return setups


SETUPS: dict[str, WaveformSetup] = load_setups()


# ---------------------------------------------------------------------------
# Configure + read-back verification (mirrors the scope library).
# ---------------------------------------------------------------------------
@dataclass
class Setting:
    label: str        # the SCPI header, e.g. "SOURce1:FREQuency"
    expected: Any     # the value we wrote
    query: str        # the query to read it back, e.g. "SOURce1:FREQuency?"


@dataclass
class CheckResult:
    label: str
    expected: Any
    readback: str
    ok: bool


def _channel_number(text: str) -> int:
    digits = "".join(c for c in text if c.isdigit())
    return int(digits) if digits else 1


def configure(afg: SocketAFG, setup: WaveformSetup,
              channels: list[int] | None = None) -> list[Setting]:
    """Apply a waveform setup to one or more channels; return what was applied.

    This ONLY sets waveform parameters (shape/frequency/amplitude/offset/duty/phase/
    impedance). It does NOT switch any output on - call output_on() for that.
    """
    if channels is None:
        channels = sorted(setup.channels) or [1]
    settings: list[Setting] = []

    def apply(base: str, value: Any) -> None:
        afg.write(f"{base} {value}")
        settings.append(Setting(base, value, f"{base}?"))

    for n in channels:
        cw = setup.channels.get(n, setup.default_channel)
        src = f"SOURce{n}"
        if cw.shape:
            apply(f"{src}:FUNCtion:SHAPe", cw.shape)
        if cw.impedance is not None:
            # Set the LOAD first. The AFG interprets amplitude/offset RELATIVE to the load,
            # so if the load changes afterwards it rescales them (e.g. doubling for high-Z),
            # and the read-back no longer matches what we set.
            apply(f"OUTPut{n}:IMPedance", cw.impedance)      # 50, or INFinity for high-Z
        if cw.frequency is not None:
            apply(f"{src}:FREQuency", cw.frequency)
        if cw.amplitude is not None:
            apply(f"{src}:VOLTage:AMPLitude", cw.amplitude)
        if cw.offset is not None:
            apply(f"{src}:VOLTage:OFFSet", cw.offset)
        if cw.duty_cycle is not None:
            if (cw.shape or "").upper().startswith("RAMP"):
                apply(f"{src}:FUNCtion:RAMP:SYMMetry", cw.duty_cycle)  # triangle/ramp symmetry
            else:
                apply(f"{src}:PULSe:DCYCle", cw.duty_cycle)            # pulse/square duty
        if cw.phase is not None:
            apply(f"{src}:PHASe:ADJust", cw.phase)           # degrees
        # Pulse by levels (PERiod before WIDTh, since width must be < period).
        if cw.pulse_rate is not None:
            apply(f"{src}:PULSe:PERiod", cw.pulse_rate)      # seconds (pulse period)
        if cw.pulse_width is not None:
            apply(f"{src}:PULSe:WIDTh", cw.pulse_width)      # seconds
        if cw.pulse_high_voltage is not None:
            apply(f"{src}:VOLTage:HIGH", cw.pulse_high_voltage)
        if cw.pulse_low_voltage is not None:
            apply(f"{src}:VOLTage:LOW", cw.pulse_low_voltage)

    return settings


def _matches(expected: Any, readback: str) -> bool:
    """Compare a written value against its read-back, tolerant of formatting."""
    text = readback.strip().strip('"')
    if isinstance(expected, (int, float)):
        try:
            got = float(text)
        except ValueError:
            return False
        return abs(got - float(expected)) <= 1e-9 + 1e-3 * abs(float(expected))
    exp_s = str(expected).strip().strip('"').upper()
    got_s = text.upper()
    if exp_s.startswith("INF"):
        # A high-Z ("INFinity") load reads back either as "INF..." or as a huge number
        # (the AFG reports infinity as e.g. 9.9E37), so accept both.
        try:
            return abs(float(text)) >= 1e30
        except ValueError:
            return got_s.startswith("INF")
    return exp_s == got_s or exp_s.startswith(got_s) or got_s.startswith(exp_s)


def verify(afg: SocketAFG, settings: list[Setting]) -> list[CheckResult]:
    """Read every applied setting back off the AFG and compare it to what we wrote."""
    results: list[CheckResult] = []
    for s in settings:
        readback = afg.query(s.query)
        results.append(CheckResult(s.label, s.expected, readback, _matches(s.expected, readback)))
    return results


def report(results: list[CheckResult]) -> bool:
    """Print a PASS/FAIL table; return True only if every check passed."""
    if not results:
        print("no settings to verify")
        return True
    label_w = max(len(r.label) for r in results)
    passed = sum(r.ok for r in results)
    for r in results:
        mark = "PASS" if r.ok else "FAIL"
        print(f"  [{mark}] {r.label:<{label_w}}  set {str(r.expected):<12} "
              f"readback {r.readback}")
    total = len(results)
    print(f"\n{passed}/{total} settings verified - "
          f"{'ALL PASSED' if passed == total else 'SOME FAILED'}")
    return passed == total


# ---------------------------------------------------------------------------
# Output control - EXPLICIT. Nothing else in this file turns an output on.
# ---------------------------------------------------------------------------
def output_on(afg: SocketAFG, channel: int = 1) -> None:
    """Switch a channel's output ON. This drives real hardware - call it deliberately."""
    afg.write(f"OUTPut{channel}:STATE ON")


def output_off(afg: SocketAFG, channel: int = 1) -> None:
    """Switch a channel's output OFF."""
    afg.write(f"OUTPut{channel}:STATE OFF")


def all_outputs_off(afg: SocketAFG, max_channels: int = 2) -> None:
    """Switch every output OFF - a safe way to leave the bench."""
    for n in range(1, max_channels + 1):
        output_off(afg, n)


def output_state(afg: SocketAFG, channel: int = 1) -> bool:
    """True if the channel's output is currently ON."""
    return afg.query(f"OUTPut{channel}:STATE?").strip().upper() in ("1", "ON")


# ---------------------------------------------------------------------------
# Command-line interface.
# ---------------------------------------------------------------------------
def _print_setups() -> None:
    for name in sorted(SETUPS):
        s = SETUPS[name]
        print(f"  {name}")
        chans = sorted(s.channels) or ["default"]
        for n in chans:
            cw = s.channels.get(n, s.default_channel) if n != "default" else s.default_channel
            bits = []
            if cw.shape: bits.append(str(cw.shape))
            if cw.frequency is not None: bits.append(f"{cw.frequency:g} Hz")
            if cw.amplitude is not None: bits.append(f"{cw.amplitude:g} Vpp")
            if cw.offset is not None: bits.append(f"offset {cw.offset:g} V")
            if cw.duty_cycle is not None: bits.append(f"duty {cw.duty_cycle:g}%")
            label = f"CH{n}" if n != "default" else "default"
            print(f"      {label:<8}: {', '.join(bits) or '(no settings)'}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Drive a Tektronix AFG31102 over its raw Socket Server (LAN).",
    )
    parser.add_argument("--host", default=None, help="AFG IP address (or set AFG_HOST).")
    parser.add_argument("--port", type=int, default=4000, help="Socket Server port. Default 4000.")
    parser.add_argument("--identify", action="store_true",
                        help="Query *IDN? and print the AFG's identity (the default action).")
    parser.add_argument("--configure", action="store_true",
                        help="Apply a named setup and print a read-back PASS/FAIL table.")
    parser.add_argument("--setup", default=None, metavar="NAME",
                        help="Which named setup --configure applies. See --list-setups.")
    parser.add_argument("--list-setups", action="store_true",
                        help="Print the available named setups and exit.")
    parser.add_argument("--channel", type=int, default=None,
                        help="Single channel for --configure/--output-on/--output-off.")
    parser.add_argument("--channels", default=None, metavar="LIST",
                        help="Comma-separated channels for --configure, e.g. 1,2.")
    parser.add_argument("--output-on", action="store_true",
                        help="Switch the channel's output ON (drives hardware).")
    parser.add_argument("--output-off", action="store_true",
                        help="Switch the channel's output OFF.")
    parser.add_argument("--all-off", action="store_true",
                        help="Switch every output OFF.")
    parser.add_argument("--query", default=None, metavar="SCPI",
                        help='Send a SCPI query and print the reply, e.g. "SOURce1:FREQuency?".')
    parser.add_argument("--send", default=None, metavar="SCPI",
                        help="Send a SCPI command (no reply expected).")
    parser.add_argument("--debug", action="store_true",
                        help="Print the raw, uncleaned reply from the AFG to stderr.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.list_setups:
        print("Available setups (use --setup NAME):")
        _print_setups()
        return 0

    host = args.host or os.environ.get("AFG_HOST")
    if not host:
        print("No AFG host. Pass --host <ip> or set AFG_HOST.", file=sys.stderr)
        return 2

    try:
        afg = SocketAFG(host, args.port)
    except OSError as exc:
        print(f"Could not connect to {host}:{args.port} - {exc}", file=sys.stderr)
        print("Is the AFG's Socket Server ON (Terminal mode) on that port?", file=sys.stderr)
        return 1

    # Channel list for --configure/--output-*.
    if args.channels:
        channels = [int(c) for c in args.channels.split(",") if c.strip()]
    elif args.channel is not None:
        channels = [args.channel]
    else:
        channels = [1]

    try:
        if args.send:
            afg.write(args.send)
            print(f"sent: {args.send}")
            return 0
        if args.query:
            print(afg.query(args.query, debug=args.debug))
            return 0
        if args.all_off:
            all_outputs_off(afg)
            print("all outputs OFF")
            return 0
        if args.output_on:
            for c in channels:
                output_on(afg, c)
                print(f"CH{c} output ON")
            return 0
        if args.output_off:
            for c in channels:
                output_off(afg, c)
                print(f"CH{c} output OFF")
            return 0
        if args.configure:
            if not args.setup:
                print("--configure needs --setup NAME. See --list-setups.", file=sys.stderr)
                return 2
            setup = SETUPS.get(args.setup)
            if setup is None:
                print(f"Unknown setup {args.setup!r}. Available: {', '.join(SETUPS)}",
                      file=sys.stderr)
                return 2
            cfg_channels = channels if (args.channels or args.channel is not None) \
                else (sorted(setup.channels) or [1])
            print("IDN:", afg.query("*IDN?"))
            applied = configure(afg, setup, cfg_channels)
            names = ", ".join(f"CH{c}" for c in cfg_channels)
            print(f"Applied {len(applied)} settings from setup '{setup.name}' to {names}. "
                  f"(Outputs unchanged - use --output-on to enable.)\n")
            return 0 if report(verify(afg, applied)) else 1
        # default action is identify
        print("IDN:", afg.query("*IDN?", debug=args.debug))
        return 0
    finally:
        afg.close()


if __name__ == "__main__":
    sys.exit(main())
