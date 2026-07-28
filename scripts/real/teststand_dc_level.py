#!/usr/bin/env python3
r"""Flat-voltage test: read a steady DC voltage on the scope and report the level.

Test case
---------
A steady DC voltage line is already present on the oscilloscope's channel - supplied
EXTERNALLY (the ECM, a bench supply, a battery, etc.). Nothing is generated here. This script
connects to the scope, reads that channel, and reports the measured voltage level (the mean of
the captured record), plus the ripple.

Just run this file:  python teststand_dc_level.py
(Complete the one-time bench setup first: instruments on the switch / HIL bench, powered on, the
Tektronix Socket Server on port 5025. Connect the DC source to the scope channel below.)

    Setup    -> configure the scope (dc_read: DC coupling, AUTO trigger)
    Read     -> capture_scope(...) ; scope_mean(...)   the measured voltage level
    Cleanup  -> save, disconnect
"""

from __future__ import annotations

import os
import sys

import teststand_api as ts

_HERE = os.path.dirname(os.path.abspath(__file__))


# ===========================================================================
# PARAMETERS
# ===========================================================================
PORT = 5025
RESULTS_DIR = os.path.join(_HERE, "results")

SCOPE = {"name": "oscope1", "serial": "MY64520125"}   # the scope the DC source is wired to
SCOPE_SETUP = "dc_read"
SCOPE_CHANNEL = 1                                      # channel the DC source is on


# ===========================================================================
def _rule(t: str) -> None:
    print("\n" + "=" * 74)
    print(t)
    print("=" * 74)


def main() -> int:
    # ---- Setup ----------------------------------------------------------------------------
    _rule("SETUP - connect + configure the scope")
    ts.scan_bench(PORT)
    scope = SCOPE["name"]
    if not ts.connect_matching(scope, SCOPE["serial"], PORT):
        print(f"Scope (serial {SCOPE['serial']}) not found.", file=sys.stderr)
        return 1
    print(f"  {scope} -> {ts.identify(scope)}")
    ts.configure_scope(scope, SCOPE_SETUP, str(SCOPE_CHANNEL))
    print(f"  scope '{SCOPE_SETUP}': {ts.get_scope_config_report(scope).splitlines()[-1]}")

    # ---- Read: capture the channel and measure the DC level -------------------------------
    _rule(f"READ - measuring the DC level on CH{SCOPE_CHANNEL}")
    if not ts.capture_scope(scope, str(SCOPE_CHANNEL)):
        print("  capture returned no data - is the DC source connected to this channel?",
              file=sys.stderr)
        ts.disconnect_all()
        return 1

    level = ts.scope_mean(scope, SCOPE_CHANNEL)
    ripple_mv = (ts.scope_vmax(scope, SCOPE_CHANNEL)
                 - ts.scope_vmin(scope, SCOPE_CHANNEL)) * 1000.0

    _rule("RESULT")
    print(f"  Measured voltage level:  {level:.3f} V")
    print(f"  (ripple {ripple_mv:.1f} mVpp over {ts.scope_sample_count(scope, SCOPE_CHANNEL)} samples)")

    png = ts.save_scope_png(scope, os.path.join(RESULTS_DIR, "dc_level.png"))
    csv = ts.save_scope_csv(scope, os.path.join(RESULTS_DIR, "dc_level.csv"))
    print(f"  saved {png}")
    print(f"  saved {csv}")

    # ---- Cleanup --------------------------------------------------------------------------
    _rule("CLEANUP")
    ts.disconnect_all()
    print("Sessions closed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
