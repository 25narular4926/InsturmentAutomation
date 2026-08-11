#!/usr/bin/env python3
r"""Robot Framework keyword library: capture the SCPI that Instrument_Automation generates.

The ONLY automation library used here is **Instrument_Automation** - and specifically its
combined **`teststand_api`** surface (`Instrument_Automation/src/teststand_api.py`), the same
flat API a NI TestStand sequence calls. This file adds NO device logic and NO simulated
instrument; it lets `teststand_api` run its real `configure_scope` / `configure_function_gen`
and records the SCPI those produce.

How the SCPI is generated without hardware
------------------------------------------
`teststand_api.configure_scope()` drives a connected transport: for every setting it calls
`transport.write("<SCPI> <value>")`, then reads it back with `transport.query("<SCPI>?")`.
Instead of connecting a real socket, we seed the API's session with a tiny **capture
transport** whose `write()` / `query()` just append the command to a list. So `teststand_api`
does all the generating - from its editable `configs/*.json` - and we only record and log the
exact SCPI it emits, with nothing faked.

Reading the SCPI back as plain English
--------------------------------------
So a test never has to name a raw command, the captured SCPI is parsed into vendor-neutral
"settings" - e.g. `CH1:SCAle 5.0` (Tektronix) and `:CHANnel1:SCALe 5.0` (Keysight) both become
`ch1.scale = 5.0`, and `TRIGger:A:EDGE:SLOpe FALL` / `:TRIGger:EDGE:SLOPe NEGative` both become
`trigger.slope = falling`. The resource file maps English sentences onto those settings, so the
same sentence works for either vendor.
"""

from __future__ import annotations

import datetime
import os
import re
import sys
from pathlib import Path

# --- Reach ONLY the Instrument_Automation library (its combined teststand_api) -----------
# libraries/ -> robot-InstrumentAutomation/ -> ASAM_XIL_Automation/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC = _REPO_ROOT / "Instrument_Automation" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import teststand_api as ts    # noqa: E402  the combined bench API (scopes + generators)
_fleet = ts._fleet            # the session manager teststand_api delegates to


# ===========================================================================
# SCPI header -> vendor-neutral canonical setting name.
# The header is lower-cased before matching, so one pattern covers both the
# Tektronix and Keysight spellings wherever they share a tail. {c} = channel.
# ===========================================================================
_HEADER_PATTERNS = [
    # scope - per-channel vertical
    (r":?select:ch(\d+)",                     "ch{c}.display"),
    (r":channel(\d+):disp(?:lay)?",           "ch{c}.display"),
    (r":?(?:ch|channel)(\d+):scale",          "ch{c}.scale"),
    (r":?(?:ch|channel)(\d+):offset",         "ch{c}.offset"),
    (r":?ch(\d+):position",                   "ch{c}.position"),
    (r":?(?:ch|channel)(\d+):coupling",       "ch{c}.coupling"),
    (r":?ch(\d+):termination",                "ch{c}.termination"),
    (r":channel(\d+):impedance",              "ch{c}.termination"),
    (r":?ch(\d+):bandwidth",                  "ch{c}.bandwidth"),
    # scope - horizontal / acquisition
    (r":?horizontal:mode",                    "timebase.mode"),
    (r":?horizontal:samplerate",              "timebase.sample_rate"),
    (r":?horizontal:scale",                   "timebase.scale"),
    (r":timebase:scale",                      "timebase.scale"),
    (r":?horizontal:recordlength",            "timebase.record_length"),
    (r":?horizontal:position",                "timebase.position"),
    (r":?acquire:mode",                       "acquire.mode"),
    (r":?acquire:type",                       "acquire.mode"),
    # scope - trigger
    (r":?trigger:a:type",                     "trigger.type"),
    (r":?trigger:mode",                       "trigger.type"),      # Keysight :TRIGger:MODE EDGE
    (r":?trigger:(?:a:)?edge:source",         "trigger.source"),
    (r":?trigger:a:level:ch(\d+)",            "trigger.level"),
    (r":?trigger:edge:level",                 "trigger.level"),
    (r":?trigger:(?:a:)?edge:slope",          "trigger.slope"),
    (r":?trigger:a:mode",                     "trigger.mode"),
    (r":?trigger:sweep",                      "trigger.mode"),
    # generator
    (r":?source(\d+):function:ramp:symmetry", "gen{c}.ramp_symmetry"),
    (r":?source(\d+):function:shape",         "gen{c}.shape"),
    (r":?output(\d+):impedance",              "gen{c}.impedance"),
    (r":?source(\d+):frequency",              "gen{c}.frequency"),
    (r":?source(\d+):voltage:amplitude",      "gen{c}.amplitude"),
    (r":?source(\d+):voltage:offset",         "gen{c}.offset"),
    (r":?source(\d+):voltage:high",           "gen{c}.high"),
    (r":?source(\d+):voltage:low",            "gen{c}.low"),
    (r":?source(\d+):pulse:dcycle",           "gen{c}.duty"),
    (r":?source(\d+):phase:adjust",           "gen{c}.phase"),
    (r":?source(\d+):pulse:period",           "gen{c}.pulse_period"),
    (r":?source(\d+):pulse:width",            "gen{c}.pulse_width"),
]
_HEADER_RX = [(re.compile(p), tmpl) for p, tmpl in _HEADER_PATTERNS]

# Setting suffixes that are keyword/enum values (everything else compares numerically).
_ENUM_SUFFIXES = {"display", "coupling", "mode", "type", "source", "slope",
                  "termination", "impedance", "shape"}


def _map_header(header: str) -> str | None:
    """Map one SCPI header (either vendor's spelling) to a canonical setting name."""
    h = header.strip().lower()
    for rx, tmpl in _HEADER_RX:
        m = rx.fullmatch(h)
        if m:
            return tmpl.format(c=m.group(1)) if m.groups() else tmpl
    return None


def _canon(key: str, value) -> str:
    """Normalise a value (raw SCPI OR an English word) to one canonical token, so the same
    sentence matches either vendor's spelling."""
    low = str(value).strip().strip('"').lower()
    suffix = key.rsplit(".", 1)[-1]
    if key.endswith("acquire.mode"):
        return ("sample" if low.startswith(("sam", "norm")) else "peak" if "peak" in low
                else "hires" if ("hir" in low or "hres" in low) else "average"
                if low.startswith(("ave", "aver")) else "envelope" if "env" in low else low)
    if key.endswith("trigger.mode"):
        return "auto" if low.startswith("auto") else "normal" if low.startswith("norm") else low
    if key.endswith("timebase.mode"):
        return "manual" if low.startswith("man") else "auto" if low.startswith("auto") else low
    if suffix == "coupling":
        return "dc" if low.startswith("dc") else "ac" if low.startswith("ac") else low
    if suffix == "slope":
        return ("rising" if low.startswith(("ris", "pos")) else
                "falling" if low.startswith(("fall", "neg")) else low)
    if suffix == "source":
        digits = re.sub(r"\D", "", low)
        return digits or low
    if suffix == "type":
        return "edge" if "edge" in low else low
    if suffix in ("termination", "impedance"):
        if "meg" in low or "high" in low or "inf" in low:
            return "high"
        if "50" in low or "fif" in low:
            return "50"
        try:
            f = float(low)
            return "high" if f >= 1e5 else "50" if abs(f - 50) < 1 else low
        except ValueError:
            return low
    if suffix == "shape":
        return {"sin": "sine", "squ": "square", "pul": "pulse", "ram": "ramp",
                "tri": "triangle", "eme": "arbitrary", "arb": "arbitrary"}.get(low[:3], low)
    if suffix == "display":
        return "on"
    return low


def _num_close(a, b) -> bool:
    try:
        fa = float(str(a).strip().strip('"'))
        fb = float(str(b).strip().strip('"'))
    except ValueError:
        return str(a).strip() == str(b).strip()
    return abs(fa - fb) <= 1e-6 + 1e-3 * abs(fb)


def _parse_settings(records: list[tuple[str, str]]) -> dict[str, str]:
    """Turn captured writes into {canonical_key: raw_value}. Generator settings also get a
    channel-agnostic alias (gen.shape ...) taken from the lowest configured channel, so a
    single-channel test can just say 'the waveform shape ...' without naming a channel."""
    settings: dict[str, str] = {}
    for kind, cmd in records:
        if kind != "W":
            continue
        parts = cmd.split(None, 1)
        value = parts[1].strip() if len(parts) > 1 else ""
        key = _map_header(parts[0])
        if not key:
            continue
        settings[key] = value
        if key.startswith("gen") and "." in key:
            settings.setdefault("gen." + key.split(".", 1)[1], value)
    return settings


class _CaptureTransport:
    """Stands in for a connected SocketScope/SocketAFG and RECORDS commands instead of sending.

    Exposes only what teststand_api's configure path touches: a `vendor` attribute (the scope
    library branches Tektronix vs Keysight on it) plus `write()` / `query()` that append to an
    ordered log. A recorder, not a simulator - queries return "" (the read-back verdict is
    irrelevant here; we only want the commands teststand_api emits)."""

    def __init__(self, vendor: str = "tektronix") -> None:
        self.vendor = vendor
        self.host = "capture"
        self.idn = ""
        self.records: list[tuple[str, str]] = []   # ("W", cmd) writes, then ("Q", cmd) queries

    def write(self, cmd: str) -> None:
        self.records.append(("W", cmd))

    def query(self, cmd: str) -> str:
        self.records.append(("Q", cmd))
        return ""

    def query_raw(self, cmd: str) -> str:
        self.records.append(("Q", cmd))
        return ""

    def close(self) -> None:
        pass


class ScpiCapture:
    """Capture, decode, and log the SCPI that Instrument_Automation's teststand_api produces."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(self) -> None:
        self._captured: list[str] = []
        self._settings: dict[str, str] = {}
        self._meta: str = ""
        self._last: dict = {}

    # --- generation (delegated to teststand_api) -----------------------------------------
    def generate_scope_configure_scpi(self, setup: str = "bench_full", channels: str = "",
                                      duration_s: float = 0.0,
                                      vendor: str = "tektronix") -> list[str]:
        """Generate the SCPI for `teststand_api.configure_scope()` and capture it.

        channels : "" uses the channels the setup itself defines (configs are data);
                   or force them with "1" / "1,2".
        """
        cap = _CaptureTransport(vendor=vendor)
        alias = "__capture_scope__"
        _fleet._scopes[alias] = cap
        try:
            ts.configure_scope(alias, setup, str(channels), float(duration_s))
        finally:
            _fleet._scopes.pop(alias, None)
            _fleet._reports.pop(alias, None)
            _fleet._record_length.pop(alias, None)

        self._ingest(cap.records)
        self._last = {"kind": "scope", "setup": setup, "vendor": vendor}
        self._meta = (f"SCOPE configure  |  setup={setup}  channels={channels or 'from config'}"
                      f"  duration_s={duration_s}  vendor={vendor}")
        return self._captured

    def generate_generator_configure_scpi(self, setup: str = "sine_1k",
                                          channels: str = "") -> list[str]:
        """Generate the SCPI for `teststand_api.configure_function_gen()` and capture it."""
        cap = _CaptureTransport()
        alias = "__capture_afg__"
        _fleet._afgs[alias] = cap
        try:
            ts.configure_function_gen(alias, setup, str(channels))
        finally:
            _fleet._afgs.pop(alias, None)
            _fleet._afg_reports.pop(alias, None)

        self._ingest(cap.records)
        self._last = {"kind": "generator", "setup": setup, "vendor": "tektronix"}
        self._meta = f"GENERATOR configure  |  setup={setup}  channels={channels or 'from config'}"
        return self._captured

    def _ingest(self, records: list[tuple[str, str]]) -> None:
        self._captured = self._transcript(records)
        self._settings = _parse_settings(records)

    @staticmethod
    def _transcript(records: list[tuple[str, str]]) -> list[str]:
        """Order the captured SCPI the way it goes out on the wire: writes, then verifies."""
        writes = [cmd for kind, cmd in records if kind == "W"]
        queries = [cmd for kind, cmd in records if kind == "Q"]
        return ["# --- apply (write) ---", *writes, "# --- verify (query) ---", *queries]

    # --- English-facing assertions (called by resources/bench.resource) ------------------
    def captured_setting_should_be(self, key: str, expected) -> None:
        """Assert a decoded setting equals `expected` (numeric-tolerant, or enum-normalised)."""
        if key not in self._settings:
            raise AssertionError(
                f"'{key}' was not in the captured SCPI. Captured: {sorted(self._settings)}")
        raw = self._settings[key]
        if key.rsplit(".", 1)[-1] in _ENUM_SUFFIXES:
            got, want = _canon(key, raw), _canon(key, expected)
            if got != want:
                raise AssertionError(
                    f"{key}: expected '{expected}' ({want}) but captured '{raw}' ({got})")
        elif not _num_close(raw, expected):
            raise AssertionError(f"{key}: expected {expected} but captured {raw}")

    def captured_setting_should_exist(self, key: str) -> None:
        """Assert a setting was applied at all (e.g. a channel was turned on)."""
        if key not in self._settings:
            raise AssertionError(
                f"'{key}' was not in the captured SCPI. Captured: {sorted(self._settings)}")

    def get_decoded_settings(self) -> dict[str, str]:
        """The full vendor-neutral view of the captured SCPI (for logging/inspection)."""
        return dict(self._settings)

    # --- capture access + logging --------------------------------------------------------
    def get_captured_scpi(self) -> list[str]:
        """The SCPI lines from the most recent generate keyword (includes the two headers)."""
        return list(self._captured)

    def get_captured_command_count(self) -> int:
        """How many real SCPI commands were captured (excludes the '# ---' header lines)."""
        return sum(1 for ln in self._captured if not ln.startswith("#"))

    def last_apply_command(self) -> str:
        """The final SET (write) command teststand_api applied - the last real line before the
        verify section. Used to prove the trigger mode is applied last."""
        apply: list[str] = []
        for ln in self._captured:
            if ln == "# --- verify (query) ---":
                break
            if not ln.startswith("#"):
                apply.append(ln)
        return apply[-1] if apply else ""

    def suggested_log_name(self) -> str:
        """A tidy filename for the last capture, e.g. 'scope_dc_read_keysight.log'."""
        stem = "{kind}_{setup}_{vendor}".format(
            kind=self._last.get("kind", "capture"), setup=self._last.get("setup", "setup"),
            vendor=self._last.get("vendor", "")).rstrip("_")
        return re.sub(r"[^A-Za-z0-9_.-]", "_", stem) + ".log"

    def write_scpi_log(self, path: str, title: str = "") -> str:
        """Write the most recent captured SCPI to `path`. Returns the absolute path."""
        path = os.path.abspath(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        head = title or self._meta or "SCPI transcript"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"# {head}\n")
            fh.write(f"# generated by Instrument_Automation.teststand_api  ({stamp})\n")
            fh.write(f"# {self._meta}\n\n")
            for ln in self._captured:
                fh.write(ln + "\n")
        return path

    # --- discovery of available configs (via teststand_api) ------------------------------
    def scope_setups(self) -> list[str]:
        """Names of the scope setups teststand_api knows (configs/*.json)."""
        return sorted(ts.list_scope_setups())

    def generator_setups(self) -> list[str]:
        """Names of the generator setups teststand_api knows (configs/*.json)."""
        return sorted(ts.list_function_gen_setups())
