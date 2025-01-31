# SpectumScan.py
Tool to comunicate with Catsniffer and `LoRa-Freq` to show a RSSI graphic in frequency range.

> This script is under development

## How to use
- Firs load to the RP2040 the firmware `LoRa-Freq` from the [CatSniffer-Firmware](https://github.com/ElectronicCats/CatSniffer-Firmware).
- Install the `requirements.txt` using the `pip install -r requirements.txt`

```bash
usage: liveSpectrumScan.py [-h] [-b BAUDRATE] [--freqStart FREQSTART] [--freqEnd FREQEND] [--offset OFFSET] port

        RadioLib SX126x_Spectrum_Scan plotter script. Displays output from SX126x_Spectrum_Scan example
        as grayscale and

        Depends on pyserial and matplotlib, install by:
        'python3 -m pip install pyserial matplotlib'

        Step-by-step guide on how to use the script:
        1. Upload the SX126x_Spectrum_Scan example to your Arduino board with SX1262 connected.
        2. Run the script with appropriate arguments.
        3. Once the scan is complete, output files will be saved to out/


positional arguments:
  port                  COM port to connect to the device

options:
  -h, --help            show this help message and exit
  -b, --baudrate BAUDRATE
                        COM port baudrate (defaults to 115200)
  --freqStart FREQSTART
                        Starting frequency in MHz (Default to 860)
  --freqEnd FREQEND     End frequency in MHz (Default to 928)
  --offset OFFSET       Default RSSI offset in dBm (defaults to -11)
```

Run with default baudrate
```bash
python3 liveSpectrumScan.py {YOUR_SERIAL_PORT}
```
Run with start frequency
```bash
python3 liveSpectrumScan.py {YOUR_SERIAL_PORT} --freqStart 915
```



## Firmware available commands
- set_start_freq: Set the frequency start range
- set_end_freq: Set the frequency end range
- start: Start the scann
- stop: Stop the scann
- get_state: Get the current state (if running)
- get_config: Get the current configuration of the radio
