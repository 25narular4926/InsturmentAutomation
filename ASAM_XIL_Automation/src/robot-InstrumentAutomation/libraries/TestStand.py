#!/usr/bin/env python3
r"""Robot Framework keyword library: run whole teststand_api WORKFLOWS and map any
teststand_api function to natural language.

This is the second half of the proof of concept. The SCPI-capture suites proved a readable
step produces the right SCPI; this proves it also produces the right FUNCTION CALLS - the same
`teststand_api` functions a NI TestStand sequence would call, in the right order - and that any
function in `teststand_api` can be reached by a plain-English phrase.

Two capabilities:

  1. Workflow execution + call recording. Every step goes through `invoke()`, which records the
     `teststand_api` call (name + args) and then actually runs it against an offline fake
     instrument (fake_instrument.py). So a workflow like connect -> configure -> arm ->
     capture -> save genuinely executes end-to-end with no hardware (it even saves a real CSV),
     and the recorded call list proves the right functions ran in the right order.

  2. Natural-language function reference. `function_for_phrase()` maps a spoken phrase onto the
     correct `teststand_api` function - for EVERY public function, by introspection - and
     `call_signature_for_phrase()` gives back the exact call signature. Deterministic: a lookup
     over the real function names plus a few curated synonyms, no LLM.

The ONLY automation library used is `teststand_api` (Instrument_Automation). The fake instrument
is a transport backend, not a second automation library.
"""

from __future__ import annotations

import inspect
import os
import re
import sys
from pathlib import Path

# --- Reach ONLY the Instrument_Automation library (its combined teststand_api) -----------
# Walk up from this file until we find Instrument_Automation/src, so the PoC keeps working
# wherever this folder is moved to in the tree.
def _find_instrument_src() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "Instrument_Automation" / "src"
        if candidate.is_dir():
            return candidate
    raise RuntimeError(f"Could not locate Instrument_Automation/src above {__file__}")


_SRC = _find_instrument_src()
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import teststand_api as ts    # noqa: E402  the combined bench API
_fleet = ts._fleet            # its session manager
import fake_instrument        # noqa: E402  offline transport backend
import ScpiCapture            # noqa: E402  reuse its SCPI-decode helpers


# ===========================================================================
# Natural-language phrase <-> teststand_api function.
# ===========================================================================
# Filler words dropped before matching, so "I want to configure the scope please" and
# "configure scope" resolve the same. Kept small so it never eats a meaningful token.
_FILLER = {"a", "an", "the", "to", "of", "for", "on", "with", "and", "my", "me", "i",
           "please", "it", "should", "be", "able", "give", "get", "do", "call", "then",
           "want", "let", "lets", "us", "can", "you", "that", "this", "make", "run"}

# Token synonyms so everyday words hit the function-name vocabulary.
_TOKEN_SYN = {"oscilloscope": "scope", "osc": "scope", "scopes": "scope",
              "generator": "gen", "funcgen": "gen", "afg": "gen", "generators": "gen",
              "func": "function", "waveform": "", "wave": "", "instrument": "",
              "instruments": "", "device": "", "devices": "", "bench": "bench"}

# A plain-English phrase for EVERY teststand_api function. This is the ledger that proves the
# whole API is expressible in natural language (no user ever needs a function name), and it
# feeds the resolver. The executable, argument-carrying sentences live in resources/actions.
_ACTION_PHRASES = {
    # detection / connection
    "detect_bench": "find every instrument on the bench",
    "scan_bench": "scan the bench without connecting",
    "connect_scope": "connect to the scope by address",
    "connect_function_gen": "connect to the generator by address",
    "connect_matching": "connect by serial",
    "list_scopes": "list the connected scopes",
    "list_function_gens": "list the connected generators",
    "list_devices": "list every connected instrument",
    "is_scope": "check whether it is a scope",
    "is_function_gen": "check whether it is a generator",
    "identify": "ask the instrument to identify itself",
    # scope setup / capture
    "list_scope_setups": "list the scope setups",
    "configure_scope": "configure the scope",
    "get_scope_config_report": "read the scope configuration report",
    "capture_scope": "capture the scope",
    "arm_scope": "arm the scope",
    "read_scope": "read the armed record",
    "scope_captured_channels": "check which channels were captured",
    # scope measurements
    "scope_vmax": "measure the peak voltage",
    "scope_vmin": "measure the lowest voltage",
    "scope_mean": "measure the average voltage",
    "scope_rms": "measure the rms voltage",
    "scope_pulse_width": "measure the positive pulse width",
    "scope_pulse_width_negative": "measure the negative pulse width",
    "scope_delay": "measure the delay between two channels",
    "scope_frequency": "measure the frequency",
    "scope_period": "measure the period",
    "scope_duty_cycle": "measure the duty cycle",
    "scope_high_voltage": "measure the high level",
    "scope_low_voltage": "measure the low level",
    "scope_dc_voltage": "measure the dc level",
    "scope_sample_count": "count the captured samples",
    "scope_dt": "check the time between samples",
    "scope_t0": "check the capture start time",
    "scope_duration": "check the record duration",
    # scope save / raw
    "save_scope_csv": "save the capture as csv",
    "save_scope_png": "save the capture as a plot",
    "scope_query": "send a raw query to the scope",
    "scope_send": "send a raw command to the scope",
    # generator
    "list_function_gen_setups": "list the generator setups",
    "configure_function_gen": "configure the generator",
    "get_function_gen_config_report": "read the generator configuration report",
    "set_function_gen_waveform": "set the generator waveform",
    "set_function_gen_levels": "set the generator levels",
    "set_function_gen_dwell": "set the generator dwell times",
    "set_function_gen_modulation": "set the generator modulation",
    "load_arbitrary_waveform": "load an arbitrary waveform",
    "function_gen_output_on": "switch the generator output on",
    "function_gen_output_off": "switch the generator output off",
    "function_gen_all_off": "switch every generator output off",
    "function_gen_output_is_on": "check whether the generator output is on",
    "function_gen_query": "send a raw query to the generator",
    "function_gen_send": "send a raw command to the generator",
    # whole bench / cleanup
    "configure_detected_bench": "detect and configure the whole bench",
    "get_bench_report": "read the bench report",
    "all_function_gen_outputs_off": "switch off every generator output on the bench",
    "disconnect": "disconnect one instrument",
    "disconnect_all": "disconnect everything",
}


def _norm(text: str) -> str:
    """Lower-case, strip punctuation, apply token synonyms, drop filler -> canonical tokens."""
    words = re.sub(r"[^a-z0-9]+", " ", str(text).lower()).split()
    out = []
    for w in words:
        w = _TOKEN_SYN.get(w, w)
        if w and w not in _FILLER:
            out.append(w)
    return " ".join(out)


def _public_functions() -> dict:
    """Every public function teststand_api exposes (defined in that module)."""
    return {name: fn for name, fn in inspect.getmembers(ts, inspect.isfunction)
            if getattr(fn, "__module__", "") == "teststand_api" and not name.startswith("_")}


class TestStand:
    """Run teststand_api workflows offline and resolve any function from natural language."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(self) -> None:
        self._funcs = _public_functions()
        self._registry = self._build_registry()
        self._calls: list[tuple[str, list]] = []      # (function_name, args) in call order
        self._sessions: dict[str, fake_instrument.FakeInstrument] = {}
        self._vendor = "tektronix"
        self._last_result = None                       # value returned by the last invoke()

    # ---------------------------------------------------------------- registry -----------
    def _build_registry(self) -> dict:
        reg = {}
        for name in self._funcs:
            reg[_norm(name.replace("_", " "))] = name          # canonical: the name itself
        for name, phrase in _ACTION_PHRASES.items():           # the plain-English phrase
            if name in self._funcs:
                reg[_norm(phrase)] = name
        return reg

    def function_for_phrase(self, phrase: str) -> str:
        """The teststand_api function a natural-language phrase refers to (deterministic)."""
        key = _norm(phrase)
        if key in self._registry:
            return self._registry[key]
        ktok = set(key.split())
        # exact token-set match (word order doesn't matter)
        for name in self._funcs:
            if set(_norm(name.replace("_", " ")).split()) == ktok:
                return name
        # every word of the function name is present -> longest such name wins
        best, best_len = None, -1
        for name in self._funcs:
            ftok = set(_norm(name.replace("_", " ")).split())
            if ftok and ftok <= ktok and len(ftok) > best_len:
                best, best_len = name, len(ftok)
        if best:
            return best
        # otherwise the greatest token overlap
        best, best_score = None, 0
        for name in self._funcs:
            score = len(set(_norm(name.replace("_", " ")).split()) & ktok)
            if score > best_score:
                best, best_score = name, score
        if best:
            return best
        raise AssertionError(f"No teststand_api function matches the phrase: {phrase!r}")

    def call_signature_for_phrase(self, phrase: str) -> str:
        """The exact call signature the phrase maps to, e.g.
        'configure_scope(alias, setup=..., channels=..., duration_s=...)'."""
        name = self.function_for_phrase(phrase)
        return f"{name}{inspect.signature(self._funcs[name])}"

    def all_teststand_functions(self) -> list:
        """Every public teststand_api function name (for full-coverage checks)."""
        return sorted(self._funcs)

    def phrase_should_resolve_to(self, phrase: str, expected: str) -> None:
        got = self.function_for_phrase(phrase)
        if got != expected:
            raise AssertionError(f"'{phrase}' resolved to {got!r}, expected {expected!r}")

    def every_teststand_action_is_plain_english(self) -> int:
        """Prove the WHOLE API is expressible in plain English: every teststand_api function has
        a natural-language phrase, and each phrase resolves back to its own function. Returns the
        number of functions covered."""
        missing = [name for name in self._funcs if name not in _ACTION_PHRASES]
        if missing:
            raise AssertionError(
                f"{len(missing)} function(s) have no plain-English phrase: {missing}")
        wrong = [(phrase, name, self.function_for_phrase(phrase))
                 for name, phrase in _ACTION_PHRASES.items()
                 if self.function_for_phrase(phrase) != name]
        if wrong:
            raise AssertionError(f"phrase(s) resolve to the wrong function: {wrong}")
        return len(self._funcs)

    # ---------------------------------------------------------------- workflow -----------
    def reset_workflow(self) -> None:
        """Clear the call log and close any offline sessions (suite setup/teardown)."""
        try:
            ts.disconnect_all()
        except Exception:                              # nothing connected yet - fine
            pass
        for alias in list(self._sessions):
            _fleet._scopes.pop(alias, None)
            _fleet._afgs.pop(alias, None)
        self._sessions.clear()
        self._calls.clear()
        self._last_result = None

    def use_vendor(self, vendor: str) -> None:
        """Pick the vendor the offline fake instrument reports (tektronix / keysight)."""
        self._vendor = "keysight" if str(vendor).lower().startswith("k") else "tektronix"

    def invoke(self, function: str, *args):
        """Record a teststand_api call, then actually run it against the offline fake bench.

        `connect_matching` / `connect_scope` are served offline by injecting a FakeInstrument
        for the alias (real discovery needs the network); every other function is the genuine
        teststand_api call, driving that fake transport.
        """
        self._calls.append((function, list(args)))
        if function in ("connect_matching", "connect_scope", "connect_function_gen"):
            alias = args[0]
            fake = fake_instrument.FakeInstrument(vendor=self._vendor)
            self._sessions[alias] = fake
            if function == "connect_function_gen":
                _fleet._afgs[alias] = fake
            else:
                _fleet._scopes[alias] = fake
            self._last_result = fake.idn
            return fake.idn
        fn = self._funcs.get(function)
        if fn is None:
            raise AssertionError(f"Unknown teststand_api function: {function!r}")
        self._last_result = fn(*args)
        return self._last_result

    # ----- typed workflow steps (so bools/ints reach teststand_api correctly) -----
    def connect_matching_step(self, alias, serial, port=5025):
        return self.invoke("connect_matching", str(alias), str(serial), int(port))

    def connect_matching_generator_step(self, alias, serial, port=5025):
        """Same teststand_api function the bench uses (connect_matching auto-detects the
        driver); offline we know from the sentence it is a generator, so seed the AFG session."""
        self._calls.append(("connect_matching", [str(alias), str(serial), int(port)]))
        fake = fake_instrument.FakeInstrument(vendor=self._vendor)
        self._sessions[alias] = fake
        _fleet._afgs[alias] = fake
        self._last_result = fake.idn
        return fake.idn

    def configure_scope_step(self, alias, setup, channels="", duration_s=0.0):
        return self.invoke("configure_scope", str(alias), str(setup), str(channels),
                           float(duration_s))

    def configure_generator_step(self, alias, setup, channels=""):
        return self.invoke("configure_function_gen", str(alias), str(setup), str(channels))

    def arm_scope_step(self, alias, channels="1"):
        return self.invoke("arm_scope", str(alias), str(channels))

    def capture_scope_step(self, alias, channels="1", single=False):
        return self.invoke("capture_scope", str(alias), str(channels), 0, bool(single), 5.0)

    def read_scope_step(self, alias):
        return self.invoke("read_scope", str(alias), 0, 5.0)

    def measure_scope_step(self, alias, metric, channel=1):
        return self.invoke("scope_" + str(metric), str(alias), int(channel))

    def generator_output_on_step(self, alias, channel=1):
        return self.invoke("function_gen_output_on", str(alias), int(channel))

    def generator_output_off_step(self, alias, channel=1):
        return self.invoke("function_gen_output_off", str(alias), int(channel))

    def save_scope_csv_step(self, alias, path):
        return self.invoke("save_scope_csv", str(alias), str(path))

    def save_scope_png_step(self, alias, path):
        return self.invoke("save_scope_png", str(alias), str(path))

    def disconnect_all_step(self):
        self._last_result = ts.disconnect_all()
        self._calls.append(("disconnect_all", []))
        return self._last_result

    def measure_delay_step(self, alias, source1, source2, edge1="rising", edge2="falling"):
        return self.invoke("scope_delay", str(alias), int(source1), int(source2),
                           str(edge1), str(edge2), "forward")

    def set_generator_waveform_step(self, alias, shape, frequency, amplitude,
                                    offset=0.0, channel=1):
        return self.invoke("set_function_gen_waveform", str(alias), int(channel), str(shape),
                           float(frequency), float(amplitude), float(offset), 0.0)

    def set_generator_levels_step(self, alias, high, low, channel=1):
        return self.invoke("set_function_gen_levels", str(alias), int(channel),
                           float(high), float(low), 0.0)

    def set_generator_dwell_step(self, alias, high_dwell, low_dwell, channel=1):
        return self.invoke("set_function_gen_dwell", str(alias), int(channel),
                           float(high_dwell), float(low_dwell))

    def set_generator_modulation_step(self, alias, modulation, rate, depth, channel=1):
        return self.invoke("set_function_gen_modulation", str(alias), int(channel),
                           str(modulation), float(rate), float(depth), 0.0, "", "")

    def load_arbitrary_step(self, alias, name, channel=1):
        return self.invoke("load_arbitrary_waveform", str(alias), int(channel), str(name))

    # ---------------------------------------------------------------- result checks ------
    def the_result(self):
        """The value the last action returned."""
        return self._last_result

    def result_should_be_a_number(self):
        try:
            f = float(self._last_result)
        except (TypeError, ValueError):
            raise AssertionError(f"result {self._last_result!r} is not a number")
        if f != f:
            raise AssertionError("result is NaN")

    def result_should_be_true(self):
        if not self._last_result:
            raise AssertionError(f"result was {self._last_result!r}, expected true")

    def result_should_list_at_least(self, count):
        v = self._last_result
        if not hasattr(v, "__len__") or len(v) < int(count):
            raise AssertionError(f"result {v!r} has fewer than {count} entries")

    def result_should_mention(self, text):
        if str(text).lower() not in str(self._last_result).lower():
            raise AssertionError(f"result {self._last_result!r} does not mention {text!r}")

    # ---------------------------------------------------------------- assertions ---------
    def called_functions(self) -> list:
        """The teststand_api function names invoked so far, in order."""
        return [name for name, _ in self._calls]

    def workflow_should_have_called_in_order(self, *expected: str) -> None:
        """Assert these functions were called in exactly this order (ignoring any extras)."""
        actual = self.called_functions()
        i = 0
        for name in actual:
            if i < len(expected) and name == expected[i]:
                i += 1
        if i != len(expected):
            raise AssertionError(
                f"Expected calls in order {list(expected)} but got {actual}")

    def workflow_should_have_called(self, function: str) -> None:
        if function not in self.called_functions():
            raise AssertionError(
                f"{function!r} was never called. Calls: {self.called_functions()}")

    def last_call_should_be(self, function: str) -> None:
        calls = self.called_functions()
        if not calls or calls[-1] != function:
            raise AssertionError(f"Last call was {calls[-1:] or None}, expected {function!r}")

    # ---------------------------------------------------------------- scpi / logs --------
    def session_settings(self, alias: str) -> dict:
        """The decoded, vendor-neutral settings from all SCPI sent to one instrument."""
        fake = self._sessions.get(alias)
        return ScpiCapture._parse_settings(fake.records) if fake else {}

    def workflow_setting_should_be(self, alias: str, key: str, expected) -> None:
        settings = self.session_settings(alias)
        if key not in settings:
            raise AssertionError(f"{alias}: '{key}' not sent. Sent: {sorted(settings)}")
        raw = settings[key]
        if key.rsplit(".", 1)[-1] in ScpiCapture._ENUM_SUFFIXES:
            if ScpiCapture._canon(key, raw) != ScpiCapture._canon(key, expected):
                raise AssertionError(f"{alias} {key}: expected {expected}, sent {raw}")
        elif not ScpiCapture._num_close(raw, expected):
            raise AssertionError(f"{alias} {key}: expected {expected}, sent {raw}")

    def write_workflow_scpi_log(self, alias: str, path: str, title: str = "") -> str:
        """Write every SCPI command sent to one instrument during the workflow to a log."""
        fake = self._sessions.get(alias)
        path = os.path.abspath(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        lines = [f"{'->' if k == 'W' else '<-'} {cmd}" for k, cmd in (fake.records if fake else [])]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"# {title or alias} workflow SCPI\n")
            fh.write("# generated by Instrument_Automation.teststand_api (offline)\n\n")
            fh.write("# --- teststand_api calls, in order ---\n")
            for name, a in self._calls:
                fh.write(f"#   {name}({', '.join(map(str, a))})\n")
            fh.write("\n# --- SCPI on the wire ---\n")
            fh.write("\n".join(lines) + "\n")
        return path
