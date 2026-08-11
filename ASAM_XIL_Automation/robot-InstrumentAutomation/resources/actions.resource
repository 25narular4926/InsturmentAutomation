*** Settings ***
Documentation     A plain-English ACTION for EVERY teststand_api function. Nobody writing a
...               test types a function name or a raw command - they write a direct statement
...               like "Measure the frequency on channel 1 of my scope" and this resource turns
...               it into the right teststand_api call (recorded, and run offline against the
...               fake instrument). Statements are imperative and self-checking: a measurement
...               statement fails if the reading is not a real number; a command statement fails
...               if the call did not succeed. So a test is just a list of instructions - no
...               "when/then", no separate "should" lines.
Library           TestStand
Library           OperatingSystem
Library           Collections

*** Variables ***
${CAPTURE_FOLDER}    ${CURDIR}/../results/captures

*** Keywords ***
# small shared helper: a measurement statement reports its reading and requires a real number
Report the reading
    [Arguments]    ${label}    ${value}
    Result Should Be A Number
    Log    ${label} = ${value}

# =====================================================================================
# Detection & connection
# =====================================================================================
Find every instrument on the bench
    Invoke    detect_bench    ${5025}

Scan the bench without connecting
    Invoke    scan_bench    ${5025}

Connect to the scope "${alias}" with serial "${serial}"
    Connect Matching Step    ${alias}    ${serial}
    Result Should Be True

Connect to the scope "${alias}" at address "${host}"
    Invoke    connect_scope    ${alias}    ${host}    ${5025}
    Result Should Be True

Connect to the generator "${alias}" with serial "${serial}"
    Invoke    connect_function_gen    ${alias}    ${serial}    ${5025}
    Result Should Be True

Confirm at least one scope is connected
    Invoke    list_scopes
    Result Should List At Least    1

List the connected generators
    Invoke    list_function_gens

List every connected instrument
    Invoke    list_devices

Confirm "${alias}" is a scope
    Invoke    is_scope    ${alias}
    Result Should Be True

Confirm "${alias}" is a generator
    Invoke    is_function_gen    ${alias}
    Result Should Be True

Ask "${alias}" to identify itself
    Invoke    identify    ${alias}
    Result Should Be True

Confirm "${alias}" identifies as a "${text}" instrument
    Invoke    identify    ${alias}
    Result Should Mention    ${text}

# =====================================================================================
# Scope: setup & capture
# =====================================================================================
List the available scope setups
    Invoke    list_scope_setups

Configure the scope "${alias}" with the "${setup}" setup
    Configure Scope Step    ${alias}    ${setup}
    Result Should Be True

Configure the scope "${alias}" with the "${setup}" setup over ${seconds} seconds
    Configure Scope Step    ${alias}    ${setup}    duration_s=${seconds}
    Result Should Be True

Confirm the scope "${alias}" configuration passed
    Invoke    get_scope_config_report    ${alias}
    Result Should Mention    PASS

Capture the scope "${alias}"
    Capture Scope Step    ${alias}
    Result Should Be True

Capture the scope "${alias}" in a single shot
    Capture Scope Step    ${alias}    single=${True}
    Result Should Be True

Arm the scope "${alias}"
    Arm Scope Step    ${alias}    1,2
    Result Should Be True

Read the armed record from the scope "${alias}"
    Read Scope Step    ${alias}
    Result Should Be True

Check which channels "${alias}" captured
    Invoke    scope_captured_channels    ${alias}

# =====================================================================================
# Scope: measurements  ("Measure ... on channel N of my scope")
# =====================================================================================
Measure the frequency on channel ${n} of "${alias}"
    ${v}=    Measure Scope Step    ${alias}    frequency    ${n}
    Report the reading    ${alias} CH${n} frequency    ${v}

Measure the period on channel ${n} of "${alias}"
    ${v}=    Measure Scope Step    ${alias}    period    ${n}
    Report the reading    ${alias} CH${n} period    ${v}

Measure the duty cycle on channel ${n} of "${alias}"
    ${v}=    Measure Scope Step    ${alias}    duty_cycle    ${n}
    Report the reading    ${alias} CH${n} duty cycle    ${v}

Measure the RMS voltage on channel ${n} of "${alias}"
    ${v}=    Measure Scope Step    ${alias}    rms    ${n}
    Report the reading    ${alias} CH${n} RMS    ${v}

Measure the average voltage on channel ${n} of "${alias}"
    ${v}=    Measure Scope Step    ${alias}    mean    ${n}
    Report the reading    ${alias} CH${n} average    ${v}

Measure the peak voltage on channel ${n} of "${alias}"
    ${v}=    Measure Scope Step    ${alias}    vmax    ${n}
    Report the reading    ${alias} CH${n} peak    ${v}

Measure the lowest voltage on channel ${n} of "${alias}"
    ${v}=    Measure Scope Step    ${alias}    vmin    ${n}
    Report the reading    ${alias} CH${n} lowest    ${v}

Measure the high level on channel ${n} of "${alias}"
    ${v}=    Measure Scope Step    ${alias}    high_voltage    ${n}
    Report the reading    ${alias} CH${n} high level    ${v}

Measure the low level on channel ${n} of "${alias}"
    ${v}=    Measure Scope Step    ${alias}    low_voltage    ${n}
    Report the reading    ${alias} CH${n} low level    ${v}

Measure the DC level on channel ${n} of "${alias}"
    ${v}=    Measure Scope Step    ${alias}    dc_voltage    ${n}
    Report the reading    ${alias} CH${n} DC level    ${v}

Measure the positive pulse width on channel ${n} of "${alias}"
    ${v}=    Measure Scope Step    ${alias}    pulse_width    ${n}
    Report the reading    ${alias} CH${n} positive pulse width    ${v}

Measure the negative pulse width on channel ${n} of "${alias}"
    ${v}=    Measure Scope Step    ${alias}    pulse_width_negative    ${n}
    Report the reading    ${alias} CH${n} negative pulse width    ${v}

Measure the delay from channel ${a} to channel ${b} on "${alias}"
    ${v}=    Measure Delay Step    ${alias}    ${a}    ${b}
    Report the reading    ${alias} delay CH${a}->CH${b}    ${v}

Count the samples captured on channel ${n} of "${alias}"
    ${v}=    Measure Scope Step    ${alias}    sample_count    ${n}
    Report the reading    ${alias} CH${n} sample count    ${v}

Check the time between samples on channel ${n} of "${alias}"
    ${v}=    Measure Scope Step    ${alias}    dt    ${n}
    Report the reading    ${alias} CH${n} sample interval    ${v}

Check the start time of channel ${n} on "${alias}"
    ${v}=    Measure Scope Step    ${alias}    t0    ${n}
    Report the reading    ${alias} CH${n} start time    ${v}

Check the record duration of channel ${n} on "${alias}"
    ${v}=    Measure Scope Step    ${alias}    duration    ${n}
    Report the reading    ${alias} CH${n} record duration    ${v}

# =====================================================================================
# Scope: save & raw
# =====================================================================================
Save the "${alias}" capture as "${filename}"
    Save Scope Csv Step    ${alias}    ${CAPTURE_FOLDER}/${filename}
    Result Should Be True

Save the "${alias}" capture as a plot "${filename}"
    Save Scope Png Step    ${alias}    ${CAPTURE_FOLDER}/${filename}
    Result Should Be True

Send the raw query "${scpi}" to the scope "${alias}"
    Invoke    scope_query    ${alias}    ${scpi}

Send the raw command "${scpi}" to the scope "${alias}"
    Invoke    scope_send    ${alias}    ${scpi}

# =====================================================================================
# Function generator
# =====================================================================================
List the available generator setups
    Invoke    list_function_gen_setups

Configure the generator "${alias}" with the "${setup}" waveform
    Configure Generator Step    ${alias}    ${setup}
    Result Should Be True

Confirm the generator "${alias}" configuration passed
    Invoke    get_function_gen_config_report    ${alias}
    Result Should Mention    PASS

Set the generator "${alias}" to a ${shape} wave at ${hz} hertz and ${volts} volts
    Set Generator Waveform Step    ${alias}    ${shape}    ${hz}    ${volts}
    Result Should Be True

Set the generator "${alias}" high level to ${high} volts and low level to ${low} volts
    Set Generator Levels Step    ${alias}    ${high}    ${low}
    Result Should Be True

Set the generator "${alias}" to hold high for ${hi} seconds and low for ${lo} seconds
    Set Generator Dwell Step    ${alias}    ${hi}    ${lo}
    Result Should Be True

Set the generator "${alias}" to ${modulation} modulation at ${rate} hertz and ${depth} percent
    Set Generator Modulation Step    ${alias}    ${modulation}    ${rate}    ${depth}
    Result Should Be True

Load the arbitrary waveform "${name}" onto the generator "${alias}"
    Load Arbitrary Step    ${alias}    ${name}
    Result Should Be True

Switch the generator "${alias}" output on
    Generator Output On Step    ${alias}
    Result Should Be True

Switch the generator "${alias}" output off
    Generator Output Off Step    ${alias}
    Result Should Be True

Switch every output off on the generator "${alias}"
    Invoke    function_gen_all_off    ${alias}

Confirm the generator "${alias}" output is on
    Invoke    function_gen_output_is_on    ${alias}    ${1}
    Result Should Be True

Send the raw query "${scpi}" to the generator "${alias}"
    Invoke    function_gen_query    ${alias}    ${scpi}

Send the raw command "${scpi}" to the generator "${alias}"
    Invoke    function_gen_send    ${alias}    ${scpi}

# =====================================================================================
# Whole bench & cleanup
# =====================================================================================
Detect and configure the whole bench
    Invoke    configure_detected_bench    ${5025}

Read the bench report
    Invoke    get_bench_report

Switch off every generator output on the bench
    Invoke    all_function_gen_outputs_off

Disconnect "${alias}"
    Invoke    disconnect    ${alias}

Disconnect everything
    Disconnect All Step

# =====================================================================================
# Files & coverage
# =====================================================================================
Confirm the captured file "${filename}" exists
    File Should Exist    ${CAPTURE_FOLDER}/${filename}

Confirm every teststand_api action can be written in plain English
    [Documentation]    Completeness: every teststand_api function has a natural-language
    ...                statement that resolves to it - no function names needed anywhere.
    ${count}=    Every Teststand Action Is Plain English
    Log    ${count} teststand_api functions, each expressible as a plain-English statement
