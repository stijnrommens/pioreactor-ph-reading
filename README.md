## Pioreactor pH reading plugin

Atlas Scientific offers the EZO pH circuit that outputs a digital signal (I2C or UART) from an analog pH electrode.

This is a simple Pioreactor plugin that returns pH readings at a set duration from connected Atlas Scientific EZO pH circuits, connected to a Thermo Scientific Orion Single Junction Combination pH Electrode.

Install from the command line, see Pioreactor docs.

> [!IMPORTANT]
> After installation, you'll need to check your configuration to add the right I2C-adress. Find the section `[pH_reading.config]`, and edit parameter `i2c_channel_hex`. Normally, the EZO pH circuit should be adressed as `0x63`.


### Overview chart

This also adds a chart to your overview page that displays the pH readings per Pioreactor.
