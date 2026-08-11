#!/usr/bin/env python3
r"""Offline fake instrument - lets a WHOLE teststand_api workflow run with no hardware.

Where the SCPI-capture suites only needed `configure` (writes + read-backs), a full workflow
(connect -> configure -> arm -> capture -> save) also has to acquire a waveform and hand it
back, or `capture`/`save` have nothing to do. So this fake transport is a bit richer than a
plain recorder - it is the "fake transport + synthetic waveforms" the project's own testing
strategy calls for (see CLAUDE.md):

  * it answers *IDN? with a Tektronix identity, so connect + vendor detection work;
  * it is a generic SCPI echo (write `CH1:SCAle 5.0` -> a later `CH1:SCAle?` returns `5.0`),
    so `configure`'s read-back verification passes;
  * it reports the acquisition as already STOPPED, so arm/read complete immediately (as if the
    trigger had fired), instead of polling forever;
  * it returns a synthetic CURVe? (a few sine cycles), so `capture` builds a real Waveform and
    `save` writes a real CSV/PNG.

It still fakes NOTHING about the commands themselves - teststand_api generates every SCPI
string; this only provides plausible replies so the offline run can complete. Point the same
workflow at a real bench (don't inject this) and it drives real instruments unchanged.
"""

from __future__ import annotations

import math

_TEK_IDN = "TEKTRONIX,MSO24,C012345,CF:91.1CT FV:2.4.6"
_KS_IDN = "KEYSIGHT TECHNOLOGIES,DSO-X 3034G,MY64520125,07.50"

# Fixed preamble the synthetic curve is scaled by: volts = code * YMULT  (YOFF/YZERO = 0).
_YMULT = 0.04


class FakeInstrument:
    """In-memory stand-in for a connected SocketScope. Records every command, echoes settings,
    and serves a synthetic waveform so capture/save work offline."""

    def __init__(self, vendor: str = "tektronix") -> None:
        self.vendor = "keysight" if str(vendor).lower().startswith("k") else "tektronix"
        self.host = "offline"
        self.idn = _KS_IDN if self.vendor == "keysight" else _TEK_IDN
        self._kv: dict[str, str] = {}
        self.records: list[tuple[str, str]] = []      # ("W", cmd) / ("Q", cmd), in order

    # --- transport surface teststand_api / bench_socket use ------------------------------
    def write(self, cmd: str) -> None:
        self.records.append(("W", cmd))
        parts = cmd.split(None, 1)
        self._kv[self._key(parts[0])] = parts[1].strip() if len(parts) > 1 else ""

    def query(self, cmd: str) -> str:
        self.records.append(("Q", cmd))
        return self._answer(cmd[:-1] if cmd.endswith("?") else cmd)

    def query_raw(self, cmd: str) -> str:
        self.records.append(("Q", cmd))
        base = cmd[:-1] if cmd.endswith("?") else cmd
        if self._key(base) in ("CURVE", "WAVEFORM:DATA"):
            return self._curve()
        return self._answer(base)

    def close(self) -> None:
        pass

    # --- the tiny SCPI engine ------------------------------------------------------------
    @staticmethod
    def _key(token: str) -> str:
        return token.strip().lstrip(":").upper()

    def _points(self) -> int:
        raw = self._kv.get("DATA:STOP") or self._kv.get("WAVEFORM:POINTS") or "1000"
        try:
            return max(1, int(float(raw)))
        except ValueError:
            return 1000

    def _answer(self, base: str) -> str:
        key = self._key(base)
        if key == "*IDN":
            return self.idn
        if key == "ACQUIRE:STATE":
            return "0"                                  # STOPPED: arm/read complete at once
        if key in ("ACQUIRE:NUMACQ", "*OPC"):
            return "1"
        if key in ("BUSY", "*ESR"):
            return "0"
        if key == "ALLEV":
            return '0,"No events"'
        if key.startswith("WFMOUTPRE:"):                # Tektronix preamble fields
            return {"XINCR": "1e-05", "XZERO": "0", "PT_OFF": "0", "YMULT": str(_YMULT),
                    "YOFF": "0", "YZERO": "0", "NR_PT": str(self._points()),
                    "ENCDG": "ASCII", "BN_FMT": "RI", "BYT_NR": "2"}.get(
                        key.split(":", 1)[1], "0")
        if key.startswith("WAVEFORM:PREAMBLE"):         # Keysight preamble (10 CSV fields)
            n = self._points()
            return f"+4,+0,{n},+1,1e-05,0,0,{_YMULT},0,0"
        if key in self._kv:
            return self._kv[key]
        return "0"

    def _curve(self) -> str:
        """A synthetic capture: a few sine cycles as raw integer codes (volts = code*YMULT)."""
        n = self._points()
        cycles = 3
        codes = [round(125 * math.sin(2 * math.pi * cycles * i / n)) for i in range(n)]
        return ",".join(str(c) for c in codes)
