*** Settings ***
Documentation     Capture the SCPI that Instrument_Automation (its combined teststand_api)
...               would send for a scope 'configure' - with no hardware and nothing faked -
...               and save it to a log you can open. Each test reads like a few plain
...               sentences that talk about the SETTINGS, never the raw commands; the wording
...               maps to the library in ../resources/bench.resource, and the same sentences
...               work for a Tektronix or a Keysight scope.
Resource          ../resources/bench.resource

*** Test Cases ***
Set up a slow DC read on the Tektronix scope
    Given the bench is running with no hardware attached
    When I set up the Tektronix scope for a "dc_read" capture
    Then channel 1 should be turned on
    And channel 1 should be DC coupled
    And channel 1 should show 5 volts per division
    And channel 1 should be high impedance
    And the timebase should be in manual mode
    And the sample rate should be 500 samples per second
    And the record length should be 10000 points
    And the trigger source should be channel 1
    And the trigger mode should be auto
    And the trigger mode should be set last so it sticks
    And the SCPI should be saved to a log I can open

Set up a two-channel key-off capture over 40 seconds
    Given the bench is running with no hardware attached
    When I set up the Tektronix scope for a "bench_full" capture over 40 seconds
    Then channel 1 should show 5 volts per division
    And channel 2 should show 5 volts per division
    And channel 2 should sit at -3.5 divisions
    And the timebase should be 4 seconds per division
    And the trigger source should be channel 1
    And the trigger level should be 6.8 volts
    And the trigger should fire on the falling edge
    And the trigger mode should be normal
    And the trigger mode should be set last so it sticks
    And the SCPI should be saved to a log I can open

Set up the same DC read on a Keysight scope
    Given the bench is running with no hardware attached
    When I set up the Keysight scope for a "dc_read" capture
    Then channel 1 should show 5 volts per division
    And channel 1 should be DC coupled
    And channel 1 should be high impedance
    And the acquisition mode should be sample
    And the trigger source should be channel 1
    And the trigger mode should be auto
    And the SCPI should be saved to a log I can open
