# About our dissectors
## Lua
The Lua version of our dissector is designed for development purposes. If you want to experiment with custom builds or make modifications, this is the version to use.
## Compliled
Our compiled dissector is built specifically for Wireshark version 4.4.0. If you need to compile it for an older version of Wireshark, you will need to do so manually. For guidance, visit our [Catsniffer Wireshark repo](https://github.com/ElectronicCats/CatSniffer-Wireshark).
This version is more stable than the Lua version and offers faster processing times.

You need to add to the main path of Wireshark inside the **epan** folder:
### Files
- **Macos**: catsniffer.so
- **Windows**: catsniffer.dll
- **Linux**: catsniffer.so

> Take care, linux and macos file extension are the same but different file size.
