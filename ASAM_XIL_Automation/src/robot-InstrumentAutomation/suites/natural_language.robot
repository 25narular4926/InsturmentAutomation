*** Settings ***
Documentation     Reference ANY teststand_api function in plain English - by stating what to
...               do ("Measure the frequency on channel 1 of my scope"), never by naming a
...               function. Each statement is a direct instruction that runs offline against
...               the fake instrument and checks itself, so a test is just a list of commands.
...               The last test proves EVERY one of the ~60 functions has such a statement.
Resource          ../resources/actions.resource
Test Setup        Reset Workflow

*** Test Cases ***
Measure a captured waveform by stating what to do
    Capture a waveform on "scope1"
    Measure the frequency on channel 1 of "scope1"
    Measure the period on channel 1 of "scope1"
    Measure the duty cycle on channel 1 of "scope1"
    Measure the RMS voltage on channel 1 of "scope1"
    Measure the average voltage on channel 1 of "scope1"
    Measure the peak voltage on channel 1 of "scope1"
    Measure the high level on channel 1 of "scope1"
    Measure the DC level on channel 1 of "scope1"
    Count the samples captured on channel 1 of "scope1"

Ask the bench about itself by stating what to do
    Capture a waveform on "scope1"
    Confirm at least one scope is connected
    Confirm "scope1" is a scope
    Confirm "scope1" identifies as a "TEKTRONIX" instrument
    Confirm the scope "scope1" configuration passed

Set up a generator by stating what to do
    Connect to the generator "gen1" with serial "B011788"
    Set the generator "gen1" to a SIN wave at 1000 hertz and 2 volts
    Switch the generator "gen1" output on
    Confirm the generator "gen1" output is on
    Set the generator "gen1" to hold high for 0.95 seconds and low for 1.05 seconds
    [Teardown]    Switch every output off on the generator "gen1"

Every teststand_api function is reachable in plain English
    Confirm every teststand_api action can be written in plain English

*** Keywords ***
Capture a waveform on "${alias}"
    [Documentation]    Connect, configure and capture so there is something to measure.
    Connect to the scope "${alias}" with serial "MSO24"
    Configure the scope "${alias}" with the "bench_full" setup
    Capture the scope "${alias}"
