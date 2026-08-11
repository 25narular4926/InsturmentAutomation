*** Settings ***
Documentation     Plain-English bench vocabulary for the SCPI-capture suites.
...
...               Every keyword here reads like a spoken sentence and hides the mechanics
...               (which library call, which raw SCPI, file paths). A suite uses only these
...               sentences, so it reads like a paragraph, not a script. The assertions talk
...               about the SETTING ("the sample rate should be 500 ...") rather than the raw
...               command ("HORizontal:SAMPLERate 500.0"), and because the captured SCPI is
...               decoded to vendor-neutral settings, the SAME sentence works for a Tektronix
...               or a Keysight scope.
...
...               How Robot gets this close to natural language:
...                 * Given / When / Then / And prefixes are recognised and stripped.
...                 * "embedded arguments" let a value sit INSIDE the sentence
...                   (e.g. a "dc_read" capture, 500 samples per second).
...                 * this resource maps each sentence onto the Instrument_Automation call.
Library           ScpiCapture
Library           OperatingSystem

*** Variables ***
${LOG_FOLDER}     ${CURDIR}/../results/scpi

*** Keywords ***
# =====================================================================================
# Given - set the scene
# =====================================================================================
The bench is running with no hardware attached
    [Documentation]    Nothing to connect: teststand_api generates and we record the SCPI.
    Log    Capturing the SCPI that Instrument_Automation would send - no instrument needed.

# =====================================================================================
# When - ask teststand_api to configure something
# =====================================================================================
I set up the ${vendor} scope for a "${setup}" capture
    [Documentation]    Configure ${setup}; the channels come from the config itself.
    Generate Scope Configure Scpi    ${setup}    vendor=${vendor.lower()}

I set up the ${vendor} scope for a "${setup}" capture over ${seconds} seconds
    [Documentation]    Same, but the window is given as one number of seconds (the timebase).
    Generate Scope Configure Scpi    ${setup}    duration_s=${seconds}    vendor=${vendor.lower()}

I set up the generator for a "${setup}" waveform
    [Documentation]    Configure a function-generator waveform.
    Generate Generator Configure Scpi    ${setup}

# =====================================================================================
# Then - talk about the scope settings (vendor-neutral; no raw SCPI)
# =====================================================================================
channel ${n} should be turned on
    Captured Setting Should Exist    ch${n}.display

channel ${n} should be ${coupling} coupled
    Captured Setting Should Be    ch${n}.coupling    ${coupling}

channel ${n} should show ${volts} volts per division
    Captured Setting Should Be    ch${n}.scale    ${volts}

channel ${n} offset should be ${volts} volts
    Captured Setting Should Be    ch${n}.offset    ${volts}

channel ${n} should sit at ${divisions} divisions
    Captured Setting Should Be    ch${n}.position    ${divisions}

channel ${n} should be high impedance
    Captured Setting Should Be    ch${n}.termination    high

channel ${n} should be 50 ohm terminated
    Captured Setting Should Be    ch${n}.termination    50

channel ${n} bandwidth should be limited to ${hz} hertz
    Captured Setting Should Be    ch${n}.bandwidth    ${hz}

the timebase should be in ${mode} mode
    Captured Setting Should Be    timebase.mode    ${mode}

the sample rate should be ${rate} samples per second
    Captured Setting Should Be    timebase.sample_rate    ${rate}

the timebase should be ${seconds} seconds per division
    Captured Setting Should Be    timebase.scale    ${seconds}

the record length should be ${points} points
    Captured Setting Should Be    timebase.record_length    ${points}

the trigger position should be ${percent} percent
    Captured Setting Should Be    timebase.position    ${percent}

the acquisition mode should be ${mode}
    Captured Setting Should Be    acquire.mode    ${mode}

it should be an edge trigger
    Captured Setting Should Be    trigger.type    edge

the trigger source should be channel ${n}
    Captured Setting Should Be    trigger.source    ${n}

the trigger level should be ${volts} volts
    Captured Setting Should Be    trigger.level    ${volts}

the trigger should fire on the ${edge} edge
    Captured Setting Should Be    trigger.slope    ${edge}

the trigger mode should be ${mode}
    Captured Setting Should Be    trigger.mode    ${mode}

the trigger mode should be set last so it sticks
    [Documentation]    The very last setting applied must be the trigger/sweep mode - the
    ...                ordering that stops the edge config from resetting it (a bench rule).
    ${last}=    Last Apply Command
    Should Match Regexp    ${last}    (?i)(TRIGger:A:MODe|:TRIGger:SWEep)
    ...    msg=Expected the trigger-mode command to be applied LAST, but got: ${last}

# =====================================================================================
# Then - talk about the generator settings (channel 1 assumed unless the config differs)
# =====================================================================================
the waveform shape should be a ${shape}
    Captured Setting Should Be    gen.shape    ${shape}

the output load should be high impedance
    Captured Setting Should Be    gen.impedance    high

the output load should be 50 ohms
    Captured Setting Should Be    gen.impedance    50

the frequency should be ${hz} hertz
    Captured Setting Should Be    gen.frequency    ${hz}

the amplitude should be ${volts} volts
    Captured Setting Should Be    gen.amplitude    ${volts}

the generator offset should be ${volts} volts
    Captured Setting Should Be    gen.offset    ${volts}

the duty cycle should be ${percent} percent
    Captured Setting Should Be    gen.duty    ${percent}

the ramp symmetry should be ${percent} percent
    Captured Setting Should Be    gen.ramp_symmetry    ${percent}

the phase should be ${degrees} degrees
    Captured Setting Should Be    gen.phase    ${degrees}

the pulse period should be ${seconds} seconds
    Captured Setting Should Be    gen.pulse_period    ${seconds}

the pulse width should be ${seconds} seconds
    Captured Setting Should Be    gen.pulse_width    ${seconds}

the high level should be ${volts} volts
    Captured Setting Should Be    gen.high    ${volts}

the low level should be ${volts} volts
    Captured Setting Should Be    gen.low    ${volts}

# =====================================================================================
# Then - keep a record
# =====================================================================================
the SCPI should be saved to a log I can open
    [Documentation]    Write the captured commands to a readable file under results/scpi/.
    ${name}=    Suggested Log Name
    ${path}=    Set Variable    ${LOG_FOLDER}/${name}
    Write Scpi Log    ${path}
    File Should Exist    ${path}
    ${text}=    Get File    ${path}
    Should Contain    ${text}    generated by Instrument_Automation
    Log    Saved the SCPI to ${path}
