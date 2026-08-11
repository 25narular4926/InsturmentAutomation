*** Settings ***
Documentation     The teststand_ecm_triangle.py flow, written as plain-English instructions.
...
...               Original test case: a function generator drives a 1 mHz triangle (period
...               1000 s) into the ECM for a 20-minute run, and one Tektronix scope reads the
...               ECM output for the whole run as a single 1200 s single-shot capture, then the
...               waveform is saved. The generator needs triangle_1mhz; the scope needs
...               ecm_20min (120 s/div, beyond a Keysight's 50 s/div - so a Tektronix captures).
...
...               This suite issues the SAME teststand_api calls in the SAME order as the
...               script: scan, connect both by serial, identify, configure both, output on,
...               single-shot capture, measure (samples / peak / lowest / duration), save CSV +
...               PNG, all outputs off, disconnect. It runs offline against the fake instrument,
...               so the capture and both saved files are produced without the bench.
Resource          ../resources/workflow.resource
Test Setup        Start with a fresh bench and no hardware attached

*** Test Cases ***
Drive a 1 mHz triangle into the ECM for 20 minutes and capture the whole run
    # Setup - find the bench and connect the two instruments by serial
    Scan the bench without connecting
    Connect to the generator "funcgen1" with serial "B011788"
    Connect to the scope "ecm_scope" with serial "MSO24"
    Ask "funcgen1" to identify itself
    Ask "ecm_scope" to identify itself
    # Configure the stimulus and the capturing scope
    Configure the generator "funcgen1" with the "triangle_1mhz" waveform
    Confirm the generator "funcgen1" configuration passed
    Configure the scope "ecm_scope" with the "ecm_20min" setup
    Confirm the scope "ecm_scope" configuration passed
    # Run - induce the triangle, then capture the whole 20-minute record in one single shot
    Switch the generator "funcgen1" output on
    Capture the scope "ecm_scope" in a single shot
    # Capture + summarize (samples, peak-to-peak from peak & lowest, and the record duration)
    Count the samples captured on channel 1 of "ecm_scope"
    Measure the peak voltage on channel 1 of "ecm_scope"
    Measure the lowest voltage on channel 1 of "ecm_scope"
    Check the record duration of channel 1 on "ecm_scope"
    # Save the waveform as CSV and as a plot
    Save the "ecm_scope" capture as "ecm_triangle.csv"
    Save the "ecm_scope" capture as a plot "ecm_triangle.png"
    Confirm the captured file "ecm_scope_ecm_triangle.csv" exists
    Confirm the captured file "ecm_scope_ecm_triangle.png" exists
    # Cleanup - leave the bench safe
    Switch every output off on the generator "funcgen1"
    Disconnect everything
    # Traceability: the ordered teststand_api calls + the SCPI they sent
    Save the SCPI and the recorded calls for "ecm_scope" to a log
