# robot-InstrumentAutomation

A Robot Framework proof of concept for the **ASAM XIL Automation** project, built on top of
the **already-working `Instrument_Automation`** scope/AFG library.

It proves the pattern the XIL project will reuse: a **keyword-driven** test layer (Robot
Framework) maps a readable step 1:1 onto a thin Python library — **no LLM in the run path**,
deterministic, offline, self-documenting via Robot's HTML report. Here the library behind the
keywords is `Instrument_Automation`; when the XIL wrapper exists, the same style of suite
drives it instead (ASAM XIL .NET calls in place of SCPI).

> This is a **new, separate** folder — it does not touch the repo's existing `robot/`
> location. Everything here is self-contained.

## What it does

For a `configure` step, it makes the **`Instrument_Automation` library generate its SCPI**,
**captures** that SCPI, and **writes it to a log** you can open — with **no hardware** and
**no simulated instrument**. Every command in the log is produced by the library from its
editable `configs/*.json`, so the log is exactly what would go out on the wire.

```
suites/configure_scpi.robot   ->   results/scpi/scope_dc_read_tektronix.log
suites/generator_scpi.robot        results/scpi/scope_bench_full_tektronix.log
                                   results/scpi/scope_dc_read_keysight.log
                                   results/scpi/generator_sine_1k_tektronix.log
                                   results/scpi/generator_pulse_1k_50duty_tektronix.log
```

It covers **both** the oscilloscope and the function generator, and the plain-English
assertions work for **either scope vendor** (Tektronix or Keysight).

## The one automation library: `Instrument_Automation` (its `teststand_api`)

The **only** automation library used is `Instrument_Automation`, and specifically its combined
**`teststand_api`** surface (`Instrument_Automation/src/teststand_api.py`) — the same flat API
a NI TestStand sequence calls. This folder adds **no device logic and no fake instrument**.

How the SCPI is generated without hardware: `teststand_api.configure_scope()` /
`configure_function_gen()` drive a connected transport — for each setting they call
`transport.write("<SCPI> <value>")` and read it back with `transport.query("<SCPI>?")`.
`libraries/ScpiCapture.py` seeds the API's session with a tiny **capture transport** whose
`write()` / `query()` append the command to a list instead of touching a socket. So
`teststand_api` does all the generating; the PoC only records and logs the exact SCPI it emits
(the SET writes, then the read-back queries).

Because the scope path branches Tektronix vs Keysight on the transport's `vendor`, the suite
regenerates the same setup as both dialects — see `scope_dc_read_keysight.log`
(`:CHANnel1:SCALe`, `:TIMebase`, `:TRIGger:SWEep`).

## Reading like English — how, and how far Robot can go

The suites are written to read like a few plain sentences that **talk about the settings**,
never a raw command:

```robotframework
Set up a slow DC read on the Tektronix scope
    Given the bench is running with no hardware attached
    When I set up the Tektronix scope for a "dc_read" capture
    Then channel 1 should be DC coupled
    And channel 1 should show 5 volts per division
    And the sample rate should be 500 samples per second
    And the trigger mode should be auto
    And the trigger mode should be set last so it sticks
    And the SCPI should be saved to a log I can open
```

No test ever types `HORizontal:SAMPLERate 500.0`. Four Robot Framework techniques get us there
(this is the "make it natural" research applied):

1. **BDD prefixes.** `Given` / `When` / `Then` / `And` / `But` are recognised and stripped, so
   a step can begin like a spoken sentence. (This is built in — no library needed.)
2. **Embedded arguments.** A keyword's name can contain the argument *inside* the sentence —
   `channel ${n} should show ${volts} volts per division` matches
   `channel 1 should show 5 volts per division`. The value sits where it reads naturally.
3. **A resource vocabulary layer.** `resources/bench.resource` defines those sentences and
   hides every mechanic (which library call, which raw SCPI, file paths). The suite uses only
   the sentences, so it reads like a paragraph; the plumbing lives one layer down.
4. **Decode SCPI to vendor-neutral settings.** The library parses the captured commands into
   settings like `ch1.scale`, `trigger.slope`, `gen.frequency` — so `CH1:SCAle 5.0`
   (Tektronix) and `:CHANnel1:SCALe 5.0` (Keysight), or `TRIGger:A:EDGE:SLOpe FALL` and
   `:TRIGger:EDGE:SLOPe NEGative`, read as the **same English**. One sentence, both vendors.
   Values are compared tolerantly (numbers by closeness, keywords normalised: `NEGative` and
   `FALL` both mean "falling"), so the sentence asserts the *meaning*, not the exact text.

The full vocabulary in `resources/bench.resource` covers **every** setting the configs use —
vertical (scale/offset/position/coupling/impedance/bandwidth), timebase (mode/sample rate/
seconds-per-division/record length/trigger position), acquisition and trigger for the scope,
and shape/frequency/amplitude/offset/duty/period/width/levels/load for the generator.

**How far this can go — and the deliberate limit.** Robot is *keyword-driven*, not free-form:
a step still has to match a defined keyword, so "natural language" here means *a controlled,
readable vocabulary*, not arbitrary prose. Going fully free-form ("just type any English") would
require an NL/LLM parser in the run path — exactly what this project rejects for hardware
(latency, a service dependency, non-determinism). So BDD + embedded arguments + a resource
vocabulary is the sweet spot: it reads like talking, yet every step is deterministic and
offline. (Gherkin `.feature` files via a library like `robotframework-gherkin` are an option if
you ever want the steps in a separate business-readable file, but they buy little over the above
and add a dependency.)

## Complete workflows — proving the right *function calls*, not just SCPI

`suites/workflows.robot` runs whole teststand_api flows end to end, written **entirely in plain
English**. The **order of the sentences is the order the teststand_api calls happen** — the test
author never lists the functions or restates the order; the backend records and runs them. The
headline flow is **connect → configure → arm → capture → save**:

```robotframework
Connect to the scope "ecm_scope" with serial "MSO24"
Configure the scope "ecm_scope" with the "bench_full" setup over 40 seconds
Arm the scope "ecm_scope"
Read the armed record from the scope "ecm_scope"
Save the "ecm_scope" capture as "keyoff.csv"
Confirm channel 1 on "ecm_scope" was set to 5 volts per division
Confirm the captured file "ecm_scope_keyoff_CH1.csv" exists
```

Each line is a direct instruction (no `when`/`then`); statements that act also check themselves.

It runs **offline against a fake instrument** (`fake_instrument.py`) that echoes settings and
serves a synthetic waveform, so `capture` and `save` genuinely execute — a real CSV lands in
`results/captures/`, and `results/scpi/workflow_<alias>_<suite>.log` records (for traceability,
without the author writing any of it) both the ordered teststand_api calls and the SCPI they put
on the wire. The suite also runs the **dc-level** flow and an **ECM-triangle** flow.

`suites/ecm_triangle.robot` is a full, faithful conversion of `Instrument_Automation`'s
`teststand_ecm_triangle.py` demo script into plain English: it issues the **same teststand_api
calls in the same order** — scan, connect both instruments by serial, identify, configure the
generator (`triangle_1mhz`) and the scope (`ecm_20min`), output on, single-shot capture, measure
(samples / peak / lowest / duration), save CSV + PNG, all outputs off, disconnect. The recorded
call log matches the script call-for-call.

Point the same suite at a real bench (don't inject the fake) and the identical steps drive real
hardware.

## Reference any teststand_api function in natural language

`suites/natural_language.robot` lets you reach **any** of the ~60 `teststand_api` functions by
**describing what you want** — never by naming a function:

```robotframework
Measure the frequency on channel 1 of "scope1"
Confirm "scope1" identifies as a "TEKTRONIX" instrument
Set the generator "gen1" to a SIN wave at 1000 hertz and 2 volts
```

Each line is a direct instruction that both acts and checks itself — a measurement statement
fails if the reading is not a real number; a command statement fails if the call did not
succeed — so there are no `when`/`then` prefixes and no separate "should" lines.

`resources/actions.resource` defines one such statement for **every** teststand_api function
(measurements, connection, configure, capture/arm/save, the generator setters, raw send, whole-
bench, cleanup). Each maps to the real call and runs offline, so the readings are real. The final
test, `Confirm every teststand_api action can be written in plain English`, proves coverage is
total: the library holds a plain-English phrase for all 58 functions and checks each resolves
back to its own function (`TestStand._ACTION_PHRASES`). No test — and no engineer — ever needs a
function name.

## Run it

```bash
cd ASAM_XIL_Automation/src/robot-InstrumentAutomation
python run.py                 # run every suite in suites/
python run.py ecm_triangle    # run one suite by name
```

Outputs land in `results/`:
- `report.html` / `log.html` — Robot's traceable report (step → verdict).
- `scpi/*.log` — SCPI transcripts (configure captures + per-workflow logs).
- `captures/*.csv` — the waveforms the workflows saved offline.

## Layout

```
robot-InstrumentAutomation/
  libraries/
    ScpiCapture.py        # configure -> capture SCPI, decode to vendor-neutral settings
    TestStand.py          # run whole workflows (record the teststand_api calls) + resolve
                          #   any function from natural language
    fake_instrument.py    # offline transport: echoes settings, serves a synthetic waveform
  resources/
    bench.resource        # plain-English vocabulary for scope/generator SETTINGS
    actions.resource      # a plain-English ACTION sentence for every teststand_api function
    workflow.resource     # workflow-specific checks layered on actions.resource
  suites/
    configure_scpi.robot  # scope configure suite (dc_read, bench_full, both vendors)
    generator_scpi.robot  # function-generator configure suite (sine, pulse)
    workflows.robot       # complete flows in plain English: arm/capture, dc-level, gen+scope
    ecm_triangle.robot    # plain-English conversion of teststand_ecm_triangle.py (same calls)
    natural_language.robot # reach any teststand_api function by describing what you want
  run.py                  # convenience runner (output -> results/)
  results/                # generated: report/log + SCPI logs + saved captures (gitignored)
```

## Keyword layers

| Layer | Example | Role |
| --- | --- | --- |
| Suite (`.robot`) | `Then channel 1 should show 5 volts per division` | reads like English, talks settings |
| Resource (`.resource`) | `channel ${n} should show ${volts} volts per division` | sentence → decoded setting |
| Library (`ScpiCapture.py`) | `Captured Setting Should Be  ch1.scale  5` | decodes/records SCPI, checks value |
| Automation library | `teststand_api.configure_scope(...)` | the real, already-built bench API |

## Next step toward the real project

Both the scope and generator configure suites exist. Once the ASAM XIL wrapper is built, add a
parallel suite whose same English sentences resolve to XIL `.NET` calls instead of SCPI — the
vocabulary layer (`resources/bench.resource`) is where that swap happens, so the tests
themselves don't change. See `../docs/NL-to-XIL-Test-Automation-Research.docx` for the full plan.
