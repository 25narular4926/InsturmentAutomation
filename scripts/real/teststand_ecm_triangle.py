#!/usr/bin/env python3
r"""ECM triangle-sweep test: drive a 1 mHz triangle for 20 minutes and capture the whole run.

Test case
---------
The function generator induces a 1 mHz triangle wave (period 1000 s) into the ECM for a
20-minute run. A single oscilloscope reads the ECM's output for the entire run - one 1200 s
single-shot acquisition, started with almost no delay - and this script captures and saves it.

Why the Tektronix scope: a 20-minute screen is 120 s/div (1200 s / 10 div), which is beyond the
Keysight DSO-X 3034G's 50 s/div limit. The Tektronix MSO24 handles it, so it is the capturing
scope here.

Just run this file:  python teststand_ecm_triangle.py
(Complete the one-time bench setup first: instruments on the switch/HIL bench, powered on, the
Tektronix Socket Server on port 5025.)

    Setup    -> connect + configure the generator (triangle_1mhz) and the scope (ecm_20min)
    Run      -> function_gen_output_on(...)               start the triangle into the ECM
                capture_scope(..., single=True, ...)      arm once, capture the full 1200 s
    Cleanup  -> save the waveform, outputs OFF, disconnect
"""

from __future__ import annotations

import os
import sys
import time

import teststand_api as ts

_HERE = os.path.dirname(os.path.abspath(__file__))


# ===========================================================================
# PARAMETERS
# ===========================================================================
PORT = 5025
RESULTS_DIR = os.path.join(_HERE, "results")

RUN_MINUTES = 20
RUN_SECONDS = RUN_MINUTES * 60                 # 1200 s single-shot record (= 20 min run)
CAPTURE_TIMEOUT_S = RUN_SECONDS + 180          # allow margin over the run length

# The generator that induces the stimulus into the ECM.
FUNCGEN = {"name": "funcgen1", "serial": "B011788"}
AFG_SETUP = "triangle_1mhz"
AFG_CHANNEL = 1

# The scope that reads the ECM output. MUST be the Tektronix (120 s/div > Keysight max).
SCOPE = {"name": "ecm_scope", "serial": "MSO24"}
SCOPE_SETUP = "ecm_20min"
SCOPE_CHANNEL = 1


# ===========================================================================
def _rule(t: str) -> None:
    print("\n" + "=" * 74)
    print(t)
    print("=" * 74)


def main() -> int:
    # ---- Setup: connect the two instruments -----------------------------------------------
    _rule("SETUP - connect + configure")
    ts.scan_bench(PORT)                          # refresh discovery (uses the IP cache)
    gen = FUNCGEN["name"]
    scope = SCOPE["name"]

    if not ts.connect_matching(gen, FUNCGEN["serial"], PORT):
        print(f"Function generator (serial {FUNCGEN['serial']}) not found.", file=sys.stderr)
        return 1
    if not ts.connect_matching(scope, SCOPE["serial"], PORT):
        print(f"Tektronix scope (serial {SCOPE['serial']}) not found.", file=sys.stderr)
        return 1
    print(f"  {gen}   -> {ts.identify(gen)}")
    print(f"  {scope} -> {ts.identify(scope)}")

    ok_gen = ts.configure_function_gen(gen, AFG_SETUP, str(AFG_CHANNEL))
    print(f"  generator '{AFG_SETUP}': {ts.get_function_gen_config_report(gen).splitlines()[-1]}")
    ok_scope = ts.configure_scope(scope, SCOPE_SETUP, str(SCOPE_CHANNEL))
    print(f"  scope '{SCOPE_SETUP}':     {ts.get_scope_config_report(scope).splitlines()[-1]}")
    if not (ok_gen and ok_scope):
        print("  (some settings were adjusted by the instrument - see the reports; the "
              "capture still runs.)")

    # ---- Run: induce the triangle, then capture the whole 20-minute record ----------------
    _rule(f"RUN - inducing a 1 mHz triangle into the ECM for {RUN_MINUTES} minutes")
    ts.function_gen_output_on(gen, AFG_CHANNEL)  # start the stimulus (drives real hardware)
    print(f"  {gen} CH{AFG_CHANNEL} output ON (1 mHz triangle, 4 Vpp, 2.5 V offset)")
    print(f"  Arming a single {RUN_SECONDS} s acquisition on {scope} and waiting for it to "
          f"fill.\n  This blocks for about {RUN_MINUTES} minutes - do not interrupt.")

    t0 = time.monotonic()
    try:
        got = ts.capture_scope(scope, str(SCOPE_CHANNEL), single=True,
                               timeout_s=CAPTURE_TIMEOUT_S)
    except TimeoutError as exc:
        print(f"  CAPTURE FAILED: {exc}", file=sys.stderr)
        ts.function_gen_all_off(gen)
        ts.disconnect_all()
        return 1
    print(f"  Captured in {time.monotonic() - t0:.0f} s.")

    # ---- Save + summarize -----------------------------------------------------------------
    _rule("CAPTURE + SAVE")
    if not got:
        print("  No waveform data returned.", file=sys.stderr)
    else:
        n = ts.scope_sample_count(scope, SCOPE_CHANNEL)
        vpp = ts.scope_vmax(scope, SCOPE_CHANNEL) - ts.scope_vmin(scope, SCOPE_CHANNEL)
        dur = ts.scope_duration(scope, SCOPE_CHANNEL)
        csv = ts.save_scope_csv(scope, os.path.join(RESULTS_DIR, "ecm_triangle.csv"))
        png = ts.save_scope_png(scope, os.path.join(RESULTS_DIR, "ecm_triangle.png"))
        print(f"  {n} pts over {dur:.0f} s   Vpp={vpp:.2f} V")
        print(f"  saved {csv}")
        print(f"  saved {png}")

    # ---- Cleanup --------------------------------------------------------------------------
    _rule("CLEANUP")
    ts.function_gen_all_off(gen)
    ts.disconnect_all()
    print("Generator output OFF; sessions closed.")
    return 0 if got else 1


if __name__ == "__main__":
    sys.exit(main())
