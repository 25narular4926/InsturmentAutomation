*** Settings ***
Documentation     Complete teststand_api workflows written as plain-English instructions. The
...               ORDER of the statements is the order the teststand_api calls happen - the
...               author never lists the functions or restates the order; the backend records
...               and runs them. Everything runs offline against a fake instrument, so capture
...               and save really execute (a real CSV lands in results/captures/). These mirror
...               the Instrument_Automation demo scripts (arm/capture, dc level, ECM triangle).
Resource          ../resources/workflow.resource
Test Setup        Start with a fresh bench and no hardware attached

*** Test Cases ***
Arm and capture a key-off event, then save
    Connect to the scope "ecm_scope" with serial "MSO24"
    Configure the scope "ecm_scope" with the "bench_full" setup over 40 seconds
    Arm the scope "ecm_scope"
    Read the armed record from the scope "ecm_scope"
    Save the "ecm_scope" capture as "keyoff.csv"
    Confirm channel 1 on "ecm_scope" was set to 5 volts per division
    Confirm the captured file "ecm_scope_keyoff_CH1.csv" exists
    Save the SCPI and the recorded calls for "ecm_scope" to a log

Read a DC level and save
    Connect to the scope "oscope1" with serial "MY64520125"
    Configure the scope "oscope1" with the "dc_read" setup
    Capture the scope "oscope1"
    Measure the average voltage on channel 1 of "oscope1"
    Save the "oscope1" capture as "dc_level.csv"
    Disconnect everything
    Confirm the captured file "oscope1_dc_level.csv" exists

Drive a generator into the ECM and capture the scope
    Connect to the generator "funcgen1" with serial "B011788"
    Connect to the scope "ecm_scope" with serial "MSO24"
    Configure the generator "funcgen1" with the "sine_1k" waveform
    Configure the scope "ecm_scope" with the "bench_full" setup
    Switch the generator "funcgen1" output on
    Capture the scope "ecm_scope" in a single shot
    Save the "ecm_scope" capture as "ecm_run.csv"
    Switch the generator "funcgen1" output off
    Disconnect everything
    Confirm the captured file "ecm_scope_ecm_run.csv" exists
