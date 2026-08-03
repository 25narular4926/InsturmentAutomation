#!/usr/bin/env python3
r"""ONE combined TestStand API for the whole bench: oscilloscopes AND function generators.

This is the single module a TestStand sequence points at. You call these functions as steps
and fill in their parameters - no glue code, no imports on your side. It combines the two
device libraries (the oscilloscope library in ./oscilloscope and the function-generator
library in ./function_generator) behind one flat, clearly-named surface:

    detect_bench(...)                 -> find every scope + generator on the bench, open sessions
    configure_scope(alias, ...)       -> apply a scope setup and verify every setting read back
    configure_function_gen(alias, ...)-> apply a generator setup and verify every setting
    function_gen_output_on(alias, ...)-> enable a generator output (explicit - drives hardware)
    capture_scope(alias, ...)         -> pull a waveform; scope_vmax/scope_rms/... read features
    disconnect_all()                  -> close every session (Cleanup)

Every function takes an `alias` (the device's name from detect_bench) as its first argument
and takes/returns ONLY primitive types (str / int / float / bool / list), so TestStand can
bind them straight to sequence variables.

Naming convention so a mixed bench is unambiguous:
    configure_scope / capture_scope / scope_*          -> oscilloscope steps
    configure_function_gen / function_gen_*            -> function-generator steps
    detect_bench / list_* / disconnect_*               -> whole-bench steps

Session state lives in the fleet layer this delegates to, so all these functions share one
set of open connections keyed by alias.

Quickest possible sequence (detect, configure everything, prove it, clean up):
    Setup:    detect_bench(5025)                 -> ["DSO-X 3034G_102", "AFG31102_72", ...]
    Main:     configure_detected_bench(5025)     -> Boolean pass/fail (report in get_bench_report)
    Cleanup:  all_function_gen_outputs_off()
              disconnect_all()
"""

from __future__ import annotations

import os
import sys

# Reach the two device libraries. The fleet layer (in ./oscilloscope) already imports the
# oscilloscope library (bench_socket), the discovery helper, AND the function-generator
# library (afg_socket, from ./function_generator) - so importing it wires up both folders.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCOPE_DIR = os.path.join(_HERE, "oscilloscope")
if _SCOPE_DIR not in sys.path:
    sys.path.insert(0, _SCOPE_DIR)

import teststand_fleet_api as _fleet   # noqa: E402  (session manager for both device types)


# Default SCPI port for this bench: every instrument is set to 5025. Pass 0 to any detect/
# connect function to probe BOTH 4000 (Tek Socket Server) and 5025 (LXI raw) instead.
DEFAULT_PORT = 5025

# Accumulated evidence text from the last configure_detected_bench().
_bench_report: str = ""


# ===========================================================================
# DETECTION + CONNECTION  (TestStand: Setup)
# ===========================================================================
def detect_bench(port: int = DEFAULT_PORT, subnet: str = "") -> list[str]:
    """Detect every instrument on the bench and open a session to each with the right driver.

    Scopes are driven by the oscilloscope library, function generators by the function-
    generator library - detected automatically from each device's *IDN?. Also probes the OS
    ARP/neighbor table, so link-local (169.254.x.x) instruments on different /24s are found.

    port   : SCPI port to probe/connect (default 5025). Pass 0 to probe both 4000 and 5025.
    subnet : "" = auto-detect; or a CIDR like "192.168.1.0/24".
    Returns the aliases created, e.g. ["DSO-X 3034G_102", "AFG31102_72"].
    """
    return _fleet.connect_discovered(int(port), subnet)


def scan_bench(port: int = DEFAULT_PORT, subnet: str = "") -> list[str]:
    """Discover instruments WITHOUT connecting; return a readable line per device (kind, model,
    serial, ip:port) so you can see the bench before opening sessions."""
    return _fleet.scan(int(port), subnet)


def connect_scope(alias: str, host: str, port: int = DEFAULT_PORT) -> str:
    """Open a scope session under `alias` by IP (no discovery). Returns its *IDN?."""
    return _fleet.connect_scope(alias, host, int(port))


def connect_function_gen(alias: str, host: str, port: int = DEFAULT_PORT) -> str:
    """Open a function-generator session under `alias` by IP (no discovery). Returns its *IDN?."""
    return _fleet.connect_generator(alias, host, int(port))


def connect_matching(alias: str, match: str, port: int = DEFAULT_PORT, subnet: str = "") -> str:
    """Discover, then open the instrument whose *IDN? contains `match` (usually its serial)
    under YOUR `alias`, with the right driver. Returns its *IDN?, or "" if nothing matched."""
    return _fleet.connect_matching(alias, match, int(port), subnet)


def list_scopes() -> list[str]:
    """Aliases of every connected oscilloscope."""
    return _fleet.list_scopes()


def list_function_gens() -> list[str]:
    """Aliases of every connected function generator."""
    return _fleet.list_generators()


def list_devices() -> list[str]:
    """Aliases of every connected instrument (scopes and generators)."""
    return _fleet.list_devices()


def is_scope(alias: str) -> bool:
    """True if the alias is a connected oscilloscope."""
    return _fleet.is_scope_alias(alias)


def is_function_gen(alias: str) -> bool:
    """True if the alias is a connected function generator."""
    return _fleet.is_generator(alias)


def identify(alias: str) -> str:
    """The instrument's *IDN? string (scope or generator)."""
    return _fleet.identify(alias)


# ===========================================================================
# OSCILLOSCOPE  (TestStand: configure / capture / measure / save)
# ===========================================================================
def list_scope_setups() -> list[str]:
    """Names of the available scope setups (from oscilloscope/configs/*.json)."""
    return _fleet.list_setups()


def configure_scope(alias: str, setup: str = "bench_full", channels: str = "1,2",
                    duration_s: float = 0.0, horizontal_scale: float = 0.0) -> bool:
    """Apply a named scope setup to one scope and verify every setting read back.

    setup            : a name from list_scope_setups(), e.g. "bench_full".
    channels         : "1" or "1,2" - which channels to configure.
    horizontal_scale : >0 sets the window width directly, in SECONDS PER DIVISION (the window
                       is horizontal_scale x 10). Overrides the setup's timebase for this call.
    duration_s       : >0 sets the window as a TOTAL time in seconds (= horizontal_scale x 10);
                       an alternative to horizontal_scale. horizontal_scale wins if both given.
    Returns True only if every setting read back correctly (see get_scope_config_report).
    """
    return _fleet.configure(alias, setup, channels, float(duration_s), float(horizontal_scale))


def get_scope_config_report(alias: str) -> str:
    """The PASS/FAIL read-back table from the last configure_scope() on this scope."""
    return _fleet.get_config_report(alias)


def capture_scope(alias: str, channels: str = "1", points: int = 0, single: bool = False,
                  timeout_s: float = 120.0) -> bool:
    """Capture one scope's channels into memory for its scope_*/save_* calls.

    channels  : "1" or "1,2".
    points    : 0 = use the record length the scope's configure set.
    single    : True arms a single acquisition and waits for a trigger (needs NORMal trigger);
                False reads the record already on the scope.
    Returns True if every requested channel returned data.
    """
    return _fleet.capture(alias, channels, int(points), bool(single), float(timeout_s))


def scope_captured_channels(alias: str) -> list[int]:
    """Which channels returned data on this scope's last capture_scope()."""
    return _fleet.captured_channels(alias)


def scope_vmax(alias: str, channel: int = 1) -> float:
    """Maximum volts on a captured channel."""
    return _fleet.get_vmax(alias, int(channel))


def scope_vmin(alias: str, channel: int = 1) -> float:
    """Minimum volts on a captured channel."""
    return _fleet.get_vmin(alias, int(channel))


def scope_mean(alias: str, channel: int = 1) -> float:
    """Mean (average) volts on a captured channel."""
    return _fleet.get_mean(alias, int(channel))


def scope_rms(alias: str, channel: int = 1) -> float:
    """True RMS volts (any shape) on a captured channel."""
    return _fleet.get_rms(alias, int(channel))


def scope_pulse_width(alias: str, channel: int = 1) -> float:
    """Positive (high) pulse width in seconds (first pulse); 0.0 if flat / no complete pulse."""
    return _fleet.get_pulse_width(alias, int(channel))


def scope_pulse_width_negative(alias: str, channel: int = 1) -> float:
    """Negative (low) pulse width in seconds (first pulse); 0.0 if flat / no complete pulse."""
    return _fleet.get_pulse_width_negative(alias, int(channel))


def scope_sample_count(alias: str, channel: int = 1) -> int:
    """How many samples were transferred on a captured channel."""
    return _fleet.get_sample_count(alias, int(channel))


def scope_dt(alias: str, channel: int = 1) -> float:
    """Seconds between consecutive samples."""
    return _fleet.get_dt(alias, int(channel))


def scope_t0(alias: str, channel: int = 1) -> float:
    """Time of the first sample (negative = before the trigger)."""
    return _fleet.get_t0(alias, int(channel))


def scope_duration(alias: str, channel: int = 1) -> float:
    """Time from the first sample to the last, in seconds."""
    return _fleet.get_duration(alias, int(channel))


def _label_path(alias: str, path: str) -> str:
    """Write the scope name into the file name so results from different scopes never collide:
    save to "results/ch1.png" from "oscope1" -> "results/oscope1_ch1.png". Idempotent - a path
    already starting with the alias is left as-is (no "oscope1_oscope1_...")."""
    folder, base = os.path.split(str(path))
    prefix = f"{alias}_"
    if not base.startswith(prefix):
        base = prefix + base
    return os.path.join(folder, base)


def save_scope_csv(alias: str, path: str) -> str:
    """Save this scope's captured data as CSV, with the scope name in the file name so results
    from different scopes are differentiated (e.g. "oscope1_ch1.csv"). Returns the path(s)."""
    return _fleet.save_csv(alias, _label_path(alias, path))


def save_scope_png(alias: str, path: str) -> str:
    """Save a PNG plot of this scope's captured data. The scope name goes in BOTH the file name
    (e.g. "oscope1_ch1.png") and the plot title, so results are differentiated. Returns path(s)."""
    return _fleet.save_png(alias, _label_path(alias, path))


def scope_query(alias: str, scpi: str) -> str:
    """Send a raw SCPI query to one scope and return the reply."""
    return _fleet.query(alias, scpi)


def scope_send(alias: str, scpi: str) -> bool:
    """Send a raw SCPI command to one scope (no reply). Always True."""
    return _fleet.send(alias, scpi)


# ===========================================================================
# FUNCTION GENERATOR  (TestStand: configure / output). Output is EXPLICIT -
# configuring a waveform never enables it; call function_gen_output_on for that.
# ===========================================================================
def list_function_gen_setups() -> list[str]:
    """Names of the available generator setups (from function_generator/configs/*.json)."""
    return _fleet.afg_list_setups()


def configure_function_gen(alias: str, setup: str = "sine_1k", channels: str = "1") -> bool:
    """Apply a named generator setup to one generator and verify every setting read back.

    Applies waveform parameters ONLY - does NOT switch any output on. Returns True only if
    every setting read back correctly (see get_function_gen_config_report).
    """
    return _fleet.afg_configure(alias, setup, channels)


def set_function_gen_waveform(alias: str, channel: int = 1, shape: str = "SIN",
                              frequency: float = 1000.0, amplitude: float = 1.0,
                              offset: float = 0.0, duty_cycle: float = 0.0) -> bool:
    """Set one generator channel's waveform directly (no named setup) and verify it.

    Pass the numbers as TestStand step parameters. duty_cycle is only sent when > 0
    (pulse/square). Does NOT switch the output on. Returns True only if every setting verified.
    """
    return _fleet.afg_set_waveform(alias, int(channel), str(shape), float(frequency),
                                   float(amplitude), float(offset), float(duty_cycle))


def get_function_gen_config_report(alias: str) -> str:
    """The PASS/FAIL read-back table from the last configure_function_gen()/set_..._waveform()."""
    return _fleet.afg_get_config_report(alias)


def function_gen_output_on(alias: str, channel: int = 1) -> bool:
    """Switch a generator channel's output ON. This drives real hardware - call it deliberately."""
    return _fleet.afg_output_on(alias, int(channel))


def function_gen_output_off(alias: str, channel: int = 1) -> bool:
    """Switch a generator channel's output OFF."""
    return _fleet.afg_output_off(alias, int(channel))


def function_gen_all_off(alias: str) -> bool:
    """Switch every output OFF on one generator."""
    return _fleet.afg_all_off(alias)


def function_gen_output_is_on(alias: str, channel: int = 1) -> bool:
    """True if the generator channel's output is currently ON."""
    return _fleet.afg_output_is_on(alias, int(channel))


def function_gen_query(alias: str, scpi: str) -> str:
    """Send a raw SCPI query to one generator and return the reply."""
    return _fleet.afg_query(alias, scpi)


def function_gen_send(alias: str, scpi: str) -> bool:
    """Send a raw SCPI command to one generator (no reply). Always True."""
    return _fleet.afg_send(alias, scpi)


# ===========================================================================
# WHOLE-BENCH CONVENIENCE  (teststand_demo as callable steps)
# ===========================================================================
def configure_detected_bench(port: int = DEFAULT_PORT, subnet: str = "",
                             scope_setup: str = "bench_full", scope_channels: str = "1,2",
                             gen_setup: str = "sine_1k", gen_channels: str = "1") -> bool:
    """Detect the whole bench, configure every scope and every generator, and build an evidence
    report (read it back with get_bench_report()). Outputs are NOT enabled.

    This is the teststand_demo flow as a single callable step. Returns True only if every
    detected instrument configured correctly.
    """
    global _bench_report
    lines: list[str] = []
    aliases = detect_bench(port, subnet)
    if not aliases:
        _bench_report = "No instruments detected. Check the link and that each SCPI socket " \
                        "is enabled on this port."
        return False

    lines.append(f"Detected {len(aliases)} instrument(s):")
    for a in aliases:
        role = "function generator" if is_function_gen(a) else "oscilloscope"
        lines.append(f"  [{role:<18}] {a:<18} {identify(a)}")

    all_ok = True
    for a in aliases:
        lines.append("")
        if is_scope(a):
            ok = configure_scope(a, scope_setup, scope_channels)
            lines.append(get_scope_config_report(a))
        else:
            ok = configure_function_gen(a, gen_setup, gen_channels)
            lines.append(get_function_gen_config_report(a))
        lines.append(f"  VERDICT: {'PASS' if ok else 'FAIL'}")
        all_ok = all_ok and ok

    lines.append("")
    lines.append("BENCH RESULT: " + ("PASS - all instruments configured correctly."
                                      if all_ok else
                                      "FAIL - one or more did not configure correctly."))
    _bench_report = "\n".join(lines)
    return all_ok


def get_bench_report() -> str:
    """The full evidence text from the last configure_detected_bench()."""
    return _bench_report


# ===========================================================================
# CLEANUP  (TestStand: Cleanup)
# ===========================================================================
def all_function_gen_outputs_off() -> bool:
    """Switch every output OFF on every connected generator. Safe blanket Cleanup."""
    return _fleet.afg_all_off_everywhere()


def disconnect(alias: str) -> bool:
    """Close whatever is connected under this alias (scope or generator)."""
    return _fleet.disconnect_device(alias)


def disconnect_all() -> bool:
    """Close every session (scopes and generators). The safe way to end the sequence."""
    return _fleet.disconnect_all()
