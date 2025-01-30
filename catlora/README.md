# Catlora
Tool to comunicate with Catsniffer and `LoRa-Freq` to show a RSSI graphic in frequency range.

> This script is under development

## How to use
- Firs load to the RP2040 the firmware `LoRa-Freq` from the [CatSniffer-Firmware](https://github.com/ElectronicCats/CatSniffer-Firmware).
- Install the `requirements.txt` using the `pip install -r requirements.txt`
- Then run the script `catlora.py`



## Firmware available commands
- set_start_freq: Set the frequency start range
- set_end_freq: Set the frequency end range
- start: Start the scann
- stop: Stop the scann
- get_state: Get the current state (if running)
- get_config: Get the current configuration of the radio