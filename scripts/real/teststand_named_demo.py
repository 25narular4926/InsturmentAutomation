#!/usr/bin/env python3
r"""Named-instrument TestStand flow with signal routing: drive two scopes from one generator.

Builds on the named-instrument pattern (bind YOUR name to a specific instrument by serial) and
adds a real routed test:

  * connect + configure each named scope (unchanged),
  * create TWO waveforms on the function generator - one per channel,
  * route AFG CH1 -> oscope1 CH1 and AFG CH2 -> oscope2 CH1,
  * capture each scope's fed channel and SAVE it with the scope's alias in the file name,
    so oscope1's and oscope2's waveforms never get mixed up.

Runs online against the bench right now:

    Setup    -> connect_matching("oscope1", serial) ; configure_scope(...)      (per scope)
    Main     -> set_function_gen_waveform("funcgen1", 1, ...)  AFG CH1 -> oscope1
                set_function_gen_waveform("funcgen1", 2, ...)  AFG CH2 -> oscope2
                function_gen_output_on(...)                    drive both signals
                capture_scope("oscope1", "1") ; save_scope_png("oscope1", results/oscope1_ch1.png)
    Cleanup  -> all_function_gen_outputs_off() ; disconnect_all()

    python teststand_named_demo.py
"""

from __future__ import annotations

import os
import sys
import time

import teststand_api as ts

_HERE = os.path.dirname(os.path.abspath(__file__))


# ===========================================================================
# PARAMETERS  (your names, the instruments they map to, and the routing)
# ===========================================================================
PORT = 5025
RESULTS_DIR = os.path.join(_HERE, "results")   # saved waveforms land here, labeled by alias

# name -> {serial (or model) of the physical scope, the setup to apply, which channels}
# signal_view is the framed setup: a fast timebase (0.5 ms/div) so a full record fills quickly
# and shows several complete cycles of the ~1 kHz signal below.
SCOPES = {
    "oscope1": {"serial": "MY64520125", "setup": "signal_view", "channels": "1,2"},
    "oscope2": {"serial": "MSO24",      "setup": "signal_view", "channels": "1"},
}

# The function generator that drives both scopes.
FUNCGEN = {"name": "funcgen1", "serial": "B011788"}

# The routing: each AFG channel makes one waveform and feeds one scope's channel. 1 kHz so a few
# full cycles fit the signal_view 5 ms window; 0-10 V (10 Vpp, 5 V offset) crosses the 5 V
# trigger; INFinity load matches the 1 MOhm scope inputs.
ROUTING = [
    {"afg_ch": 1, "scope": "oscope1", "scope_ch": 1,
     "shape": "SIN", "frequency": 1000.0, "amplitude": 10.0, "offset": 5.0, "impedance": "INFinity"},
    {"afg_ch": 2, "scope": "oscope2", "scope_ch": 1,
     "shape": "SQU", "frequency": 1000.0, "amplitude": 10.0, "offset": 5.0, "impedance": "INFinity"},
]


# ===========================================================================
def _rule(title: str) -> None:
    print("\n" + "=" * 74)
    print(title)
    print("=" * 74)


def main() -> int:
    all_ok = True

    # ---- Setup: scan, then connect + configure each NAMED scope (unchanged) ----------------
    _rule("SETUP - scan + connect + configure scopes")
    found = ts.scan_bench(PORT)
    if not found:
        print("No instruments detected. Check the link and each SCPI socket.", file=sys.stderr)
        return 1
    print(f"Found {len(found)} instrument(s):")
    for line in found:
        print(f"  {line}")

    for name, spec in SCOPES.items():
        idn = ts.connect_matching(name, spec["serial"], PORT)
        if not idn:
            print(f"  {name}: FAIL - serial {spec['serial']!r} not found on the bench.")
            all_ok = False
            continue
        ok = ts.configure_scope(name, spec["setup"], spec["channels"])
        tail = ts.get_scope_config_report(name).splitlines()[-1]
        # Config read-back is informational here (e.g. a 70 MHz MSO24 clamps a 500 MHz
        # bandwidth request); the test's verdict is about routing + capture below.
        print(f"  {name} <- {idn.split(',')[1]}  configure {spec['setup']}: "
              f"{'all verified' if ok else 'some clamped'}  ({tail})")

    # ---- Main: create the two waveforms on the generator and route them --------------------
    _rule("MAIN - create 2 waveforms on the function generator")
    gen = FUNCGEN["name"]
    idn = ts.connect_matching(gen, FUNCGEN["serial"], PORT)
    if not idn:
        print(f"  FAIL - generator serial {FUNCGEN['serial']!r} not found.", file=sys.stderr)
        return 1
    print(f"  {gen} <- {idn}")
    for r in ROUTING:
        ts.function_gen_send(gen, f"OUTPut{r['afg_ch']}:IMPedance {r['impedance']}")
        ok = ts.set_function_gen_waveform(gen, r["afg_ch"], r["shape"], r["frequency"],
                                          r["amplitude"], r["offset"])
        print(f"  AFG CH{r['afg_ch']} = {r['shape']} {r['frequency']:g} Hz {r['amplitude']:g} Vpp "
              f"offset {r['offset']:g} V  -> {r['scope']} CH{r['scope_ch']}   "
              f"{'PASS' if ok else 'FAIL'}")
        all_ok = all_ok and ok

    # Enable both outputs (explicit - drives real hardware), then let the signals settle.
    for r in ROUTING:
        ts.function_gen_output_on(gen, r["afg_ch"])
    print("  both outputs ON; settling ...")
    time.sleep(2.0)

    # ---- Capture each scope's fed channel and SAVE it labeled by alias ---------------------
    _rule("CAPTURE + SAVE (files labeled by scope alias)")
    for r in ROUTING:
        scope, ch = r["scope"], r["scope_ch"]
        if scope not in ts.list_scopes():
            print(f"  {scope}: not connected - skipping.")
            all_ok = False
            continue
        got = ts.capture_scope(scope, str(ch))
        if not got:
            print(f"  {scope} CH{ch}: capture FAILED (no data).")
            all_ok = False
            continue
        vpp = ts.scope_vmax(scope, ch) - ts.scope_vmin(scope, ch)
        rms = ts.scope_rms(scope, ch)
        # Pass a generic name; save_scope_* writes the scope's alias into the file name (and
        # the plot title) so oscope1's and oscope2's results are differentiated automatically.
        saved_csv = ts.save_scope_csv(scope, os.path.join(RESULTS_DIR, f"ch{ch}.csv"))
        saved_png = ts.save_scope_png(scope, os.path.join(RESULTS_DIR, f"ch{ch}.png"))
        print(f"  {scope} CH{ch}  (from AFG CH{r['afg_ch']}, {r['shape']}): "
              f"{ts.scope_sample_count(scope, ch)} pts  Vpp={vpp:.2f}  RMS={rms:.2f}")
        print(f"      saved {saved_csv}")
        print(f"      saved {saved_png}")

    # ---- Cleanup --------------------------------------------------------------------------
    _rule("CLEANUP")
    ts.all_function_gen_outputs_off()
    ts.disconnect_all()
    print("All generator outputs OFF; all sessions closed.")

    _rule("BENCH RESULT")
    print("PASS - scopes configured, both waveforms routed, and both captures saved."
          if all_ok else
          "FAIL - see above (a config mismatch, missing instrument, or failed capture).")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
