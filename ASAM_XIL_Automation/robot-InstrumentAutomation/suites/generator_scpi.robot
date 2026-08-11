*** Settings ***
Documentation     Same idea as configure_scpi.robot, but for the function generator: capture
...               the SCPI that Instrument_Automation's teststand_api would send to configure
...               an AFG waveform, and talk about the waveform in plain English (shape,
...               frequency, amplitude, load) rather than raw SCPI. No hardware, nothing faked.
Resource          ../resources/bench.resource

*** Test Cases ***
Set up a 1 kHz sine wave on the generator
    Given the bench is running with no hardware attached
    When I set up the generator for a "sine_1k" waveform
    Then the waveform shape should be a sine
    And the frequency should be 1000 hertz
    And the amplitude should be 2 volts
    And the generator offset should be 0 volts
    And the output load should be 50 ohms
    And the SCPI should be saved to a log I can open

Set up a 1 kHz 50 percent pulse on the generator
    Given the bench is running with no hardware attached
    When I set up the generator for a "pulse_1k_50duty" waveform
    Then the waveform shape should be a pulse
    And the frequency should be 1000 hertz
    And the amplitude should be 5 volts
    And the generator offset should be 2.5 volts
    And the duty cycle should be 50 percent
    And the output load should be high impedance
    And the SCPI should be saved to a log I can open
