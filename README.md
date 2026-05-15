# Pioreactor pH reading plugin

Atlas Scientific offers the EZO pH circuit that outputs a digital signal (I2C or UART) from an analog pH electrode.

This is a simple Pioreactor plugin that returns pH readings from the connected Atlas Scientific EZO pH circuit, connected to a Thermo Scientific Orion Single Junction Combination pH Electrode. This plugin also includes options for pH control and calibration.

## Install from source

```bash
pio plugins install pioreactor_ph_reading --source git+https://github.com/stijnrommens/pioreactor-ph-reading.git
```

> [!IMPORTANT]
> After installation, you'll need to check your configuration to add the right I2C-adress. Find the section `[pH_reading.config]`, and edit parameter `i2c_channel_hex`. Normally, the EZO pH circuit should be adressed as `0x63`. Moreover, PID settings should be checked under `[pH_regulation.config]`, and adjusted if necessary.


## Overview chart

This also adds a chart to your overview page that displays the pH readings per Pioreactor.

## Calibration protocol

A calibration protocol provided in the UI. The protocol allows you to select between a 2-point or 3-point calibration. Calibration data is saved on the EZO pH circuit.

## Dosing automation

Controlling of pH is possible by selecting `pH control` in `dosing automations`, and providing a `Target pH`. Base dosing is done via the `alt_media` pump defined under the `PWM` configuration. Note that this automation can be started once the `pH reading` job is started. It is recommended to apply the same interval as used for the pH reading itself.
