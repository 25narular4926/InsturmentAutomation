# ASAM_XIL_Automation / src

Placeholder for the future code of the readable-keyword HIL test-automation project.

Nothing is built yet. Planned structure (see ../docs research document):

- `robot/`   - Robot Framework keyword library: each readable keyword (e.g. "Induce Sine Wave")
               binds directly to a Python function. Robot Framework is the authoring + mapping
               layer - NO LLM, deterministic, offline, with built-in HTML/XML reporting.
- `xillib/`  - thin Python wrapper over the ASAM XIL .NET API (via pythonnet):
               Testbench/ports, model read/write, capture, signal generation, EES faults,
               diagnostics - the functions the keywords call.
- `configs/` - test-case data (portconfig references + our own JSON test definitions).
- `tests/`   - offline unit tests (fake XIL backend), integration tests (real HIL, opt-in).

Design mirrors the Instrument_Automation block: a thin, swappable transport (here the XIL
.NET assemblies instead of raw SCPI), one contract, config-as-data, offline-first.
