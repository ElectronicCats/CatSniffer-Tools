#!/usr/bin/env python3
"""
Meshtastic Full Config Extractor
Extract PSKs and important config info from a Meshtastic JSONC config file

Kevin Leon @ Electronic Cats
"""

import re
import argparse
import base64
import sys


def extract_hex_array(value):
    """Extract hex bytes from value"""
    hex_bytes = re.findall(r"0x[0-9a-fA-F]+", value)
    return bytes(int(b, 16) for b in hex_bytes)


def clean_jsonc(jsonc_str):
    """Remove comments from JSONC"""
    return re.sub(r"//.*", "", jsonc_str)


def extract_named_fields(data, field_patterns):
    """Extract named fields using regex patterns"""
    result = {}
    for label, pattern in field_patterns:
        match = re.search(pattern, data)
        if match:
            result[label] = match.group(1).strip().strip('"').strip("'")
    return result


def extract_channels(data):
    """Extract channel information"""
    channel_info = []
    psk_pattern = re.compile(r'"USERPREFS_CHANNEL_(\d+)_PSK"\s*:\s*"\{([^}]*)\}"')
    name_pattern = re.compile(r'"USERPREFS_CHANNEL_(\d+)_NAME"\s*:\s*"([^"]+)"')

    psks = {m.group(1): m.group(2) for m in psk_pattern.finditer(data)}
    names = {m.group(1): m.group(2) for m in name_pattern.finditer(data)}

    for ch_id, raw_psk in psks.items():
        hex_bytes = raw_psk.replace(" ", "").split(",")
        psk_bytes = bytes(int(b, 16) for b in hex_bytes)
        channel_info.append(
            {
                "channel": ch_id,
                "name": names.get(ch_id, f"Channel_{ch_id}"),
                "psk_hex": psk_bytes.hex(),
                "psk_base64": base64.b64encode(psk_bytes).decode(),
            }
        )
    return channel_info


def extract_admin_keys(data):
    """Extract admin keys"""
    keys = []
    for i in range(3):
        pattern = re.compile(rf'"USERPREFS_USE_ADMIN_KEY_{i}"\s*:\s*"\{{([^}}]*)\}}"')
        match = pattern.search(data)
        if match:
            key_bytes = bytes(int(b, 16) for b in match.group(1).split(","))
            keys.append(
                {
                    "index": i,
                    "hex": key_bytes.hex(),
                    "base64": base64.b64encode(key_bytes).decode(),
                }
            )
    return keys


class MeshtasticConfigExtractor:
    """Extract configuration from Meshtastic JSONC files"""

    def __init__(self, filepath):
        """
        Initialize extractor with config file path

        Args:
            filepath: Path to Meshtastic JSONC config file
        """
        self.filepath = filepath
        self.data = None

    def load(self):
        """Load and parse the config file"""
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                jsonc_data = f.read()
            self.data = clean_jsonc(jsonc_data)
            return True
        except Exception as e:
            print(f"Error reading file: {e}")
            return False

    def extract_channels(self):
        """Extract channel information"""
        if self.data is None:
            return []
        return extract_channels(self.data)

    def extract_general_config(self):
        """Extract general configuration"""
        if self.data is None:
            return {}
        return extract_named_fields(
            self.data,
            [
                ("LoRa Channel", r'"USERPREFS_LORACONFIG_CHANNEL_NUM"\s*:\s*"([^"]+)"'),
                (
                    "LoRa Modem Preset",
                    r'"USERPREFS_LORACONFIG_MODEM_PRESET"\s*:\s*"([^"]+)"',
                ),
                ("MQTT Address", r'"USERPREFS_MQTT_ADDRESS"\s*:\s*["\']([^"\']+)["\']'),
                ("MQTT Username", r'"USERPREFS_MQTT_USERNAME"\s*:\s*"([^"]+)"'),
                ("MQTT Password", r'"USERPREFS_MQTT_PASSWORD"\s*:\s*"([^"]+)"'),
                (
                    "MQTT Encryption",
                    r'"USERPREFS_MQTT_ENCRYPTION_ENABLED"\s*:\s*"([^"]+)"',
                ),
                ("MQTT TLS Enabled", r'"USERPREFS_MQTT_TLS_ENABLED"\s*:\s*"([^"]+)"'),
                ("MQTT Root Topic", r'"USERPREFS_MQTT_ROOT_TOPIC"\s*:\s*"([^"]+)"'),
                ("Timezone", r'"USERPREFS_TZ_STRING"\s*:\s*"([^"]+)"'),
                ("Ringtone", r'"USERPREFS_RINGTONE_RTTTL"\s*:\s*"([^"]+)"'),
            ],
        )

    def extract_oem_branding(self):
        """Extract OEM branding info"""
        if self.data is None:
            return {}
        return extract_named_fields(
            self.data,
            [
                ("OEM Text", r'"USERPREFS_OEM_TEXT"\s*:\s*"([^"]+)"'),
                ("Font Size", r'"USERPREFS_OEM_FONT_SIZE"\s*:\s*"([^"]+)"'),
                ("Image Width", r'"USERPREFS_OEM_IMAGE_WIDTH"\s*:\s*"([^"]+)"'),
                ("Image Height", r'"USERPREFS_OEM_IMAGE_HEIGHT"\s*:\s*"([^"]+)"'),
            ],
        )

    def extract_admin_keys(self):
        """Extract admin keys"""
        if self.data is None:
            return []
        return extract_admin_keys(self.data)

    def print_all(self):
        """Print all extracted information"""
        print("=== CHANNELS ===")
        channels = self.extract_channels()
        for ch in channels:
            print(f"Channel {ch['channel']}: {ch['name']}")
            print(f"  PSK (hex):     {ch['psk_hex']}")
            print(f"  PSK (base64):  {ch['psk_base64']}\n")

        print("=== GENERAL CONFIG ===")
        general_fields = self.extract_general_config()
        for k, v in general_fields.items():
            print(f"{k}: {v}")
        print()

        print("=== OEM BRANDING ===")
        oem_fields = self.extract_oem_branding()
        for k, v in oem_fields.items():
            print(f"{k}: {v}")
        print()

        print("=== ADMIN KEYS ===")
        admin_keys = self.extract_admin_keys()
        if not admin_keys:
            print("No admin keys found.\n")
        else:
            for key in admin_keys:
                print(f"Admin Key {key['index']}:")
                print(f"  Hex:    {key['hex']}")
                print(f"  Base64: {key['base64']}\n")


def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Extract PSKs and important config info from a Meshtastic JSONC config file.",
        epilog="""Examples:
  catsniffer meshtastic config device.yaml
  catsniffer meshtastic config /path/to/config.jsonc
""",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("file", help="Path to Meshtastic JSONC config file")
    args = parser.parse_args()

    extractor = MeshtasticConfigExtractor(args.file)
    if extractor.load():
        extractor.print_all()
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
