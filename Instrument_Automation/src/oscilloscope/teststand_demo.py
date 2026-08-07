#!/usr/bin/env python3
r"""A stand-in for a TestStand sequence: detect the bench, configure it, prove it landed.

This file imitates what a TestStand sequence would do by calling the same functions a
sequence would call (from teststand_fleet_api), with the same primitive parameters you would
type into TestStand step arguments. Run it as a plain script to see the whole flow and the
PASS/FAIL evidence:

    python teststand_demo.py

It maps onto a TestStand sequence like this:

    Setup    -> connect_discovered(PORT)            detect every instrument on the bench
    Main     -> configure(scope, SCOPE_SETUP, ...)  apply + read back every scope setting
                afg_configure(afg, AFG_SETUP, ...)  apply + read back every generator setting
    Cleanup  -> afg_all_off_everywhere()            leave outputs OFF (never turned them on)
                disconnect_all()

Every call here takes/returns only primitive types, exactly as TestStand needs. Edit the
PARAMETERS block below (the equivalent of TestStand step arguments) and re-run.
"""

from __future__ import annotations

import sys

import teststand_fleet_api as fleet


# ===========================================================================
# PARAMETERS  (these are the "TestStand step arguments" - edit and re-run)
# ===========================================================================
PORT = 5025                    # SCPI port every instrument listens on (0 = probe 4000 AND 5025)
SUBNET = ""                    # "" = auto-detect; discovery also probes the ARP neighbor table

SCOPE_SETUP = "bench_full"     # named setup from oscilloscope/configs/*.json
SCOPE_CHANNELS = "1,2"         # which scope channels to configure

AFG_SETUP = "sine_1k"          # named setup from function_generator/configs/*.json
AFG_CHANNELS = "1"             # which generator channels to configure


# ===========================================================================
# Helpers - just for pretty console evidence. The real work is the fleet calls.
# ===========================================================================
def _rule(title: str) -> None:
    print("\n" + "=" * 74)
    print(title)
    print("=" * 74)


def main() -> int:
    # ---- Setup: detect the bench ------------------------------------------
    _rule("SETUP - detecting instruments")
    aliases = fleet.connect_discovered(PORT, SUBNET)
    if not aliases:
        print("No instruments detected. Check the link (Ethernet up?) and that each "
              "instrument's SCPI socket is enabled on this port.", file=sys.stderr)
        return 1

    scopes = [a for a in aliases if fleet.is_scope_alias(a)]
    afgs = [a for a in aliases if fleet.is_generator(a)]
    print(f"Detected {len(aliases)} instrument(s):")
    for a in aliases:
        role = "function generator" if fleet.is_generator(a) else "oscilloscope"
        print(f"  [{role:<18}] {a:<18} {fleet.identify(a)}")
    print(f"\n  -> {len(scopes)} scope(s): {scopes or 'none'}")
    print(f"  -> {len(afgs)} generator(s): {afgs or 'none'}")

    # ---- Main: configure each instrument and capture the read-back evidence
    all_ok = True

    for alias in scopes:
        _rule(f"CONFIGURE SCOPE  {alias}  (setup '{SCOPE_SETUP}', CH {SCOPE_CHANNELS})")
        ok = fleet.configure(alias, SCOPE_SETUP, SCOPE_CHANNELS)
        all_ok = all_ok and ok
        print(fleet.get_config_report(alias))
        print(f"\n  VERDICT: {'PASS - every setting read back correctly' if ok else 'FAIL - see above'}")

    for alias in afgs:
        _rule(f"CONFIGURE GENERATOR  {alias}  (setup '{AFG_SETUP}', CH {AFG_CHANNELS})")
        ok = fleet.afg_configure(alias, AFG_SETUP, AFG_CHANNELS)
        all_ok = all_ok and ok
        print(fleet.afg_get_config_report(alias))
        print(f"\n  VERDICT: {'PASS - every setting read back correctly' if ok else 'FAIL - see above'}")
        # NOTE: the output is deliberately NOT enabled. A real sequence would call
        # fleet.afg_output_on(alias, 1) here, explicitly, when it wants to drive the signal.

    # ---- Cleanup: leave the bench safe ------------------------------------
    _rule("CLEANUP")
    fleet.afg_all_off_everywhere()      # generators: every output OFF (they were never on)
    fleet.disconnect_all()
    print("All generator outputs OFF; all sessions closed.")

    # ---- Overall verdict (the sequence's pass/fail) -----------------------
    _rule("BENCH RESULT")
    print("PASS - all instruments detected and configured correctly."
          if all_ok else
          "FAIL - one or more instruments did not configure correctly (see tables above).")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
