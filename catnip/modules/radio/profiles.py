"""Radio profiles: named bundles of the SX1262 sniff flags.

A LoRa/FSK capture needs 8-14 flags agreeing with each other (frequency,
bandwidth, spreading factor/bitrate, sync word, ...) — get one wrong and the
radio just hears nothing, with no error to point at the mistake. A profile is
a named shortcut for a known-good combination, e.g.::

    catnip sniff lora --profile eu868-meshtastic-longfast

which is exactly the same flags as::

    catnip sniff lora -freq 869525000 -bw 250 -sf 11 -cr 5 -sw 0x2B -pre 8

Built-in profiles cover the Meshtastic channel presets (extracted from
``modules/protocols/meshtastic/core.py``, which is the historical source of
truth for those SF/BW/CR/preamble combinations) crossed with a couple of
regional frequency plans. Users can add their own in
``~/.config/catnip/profiles.toml``, which take precedence over a built-in of
the same name.

A profile only ever supplies *defaults*: the caller (``modules/sniff/cli.py``)
feeds this into Click's ``ctx.default_map``, so any flag the user actually
types on the command line still wins.
"""

import os
from pathlib import Path
from typing import Dict, Optional

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib


class ProfileError(ValueError):
    """A profile name, file or field could not be resolved."""


PROFILES_ENV_VAR = "CATNIP_PROFILES_FILE"
DEFAULT_PROFILES_PATH = Path.home() / ".config" / "catnip" / "profiles.toml"

# Same table ``configure_meshtastic_radio`` used to keep to itself — "pl" is
# renamed "preamble" to match the ``sniff lora`` flag it now feeds.
MESHTASTIC_CHANNEL_PRESETS = {
    "defcon33": {"sf": 7, "bw": 500, "cr": 5, "preamble": 16},
    "ShortTurbo": {"sf": 7, "bw": 500, "cr": 5, "preamble": 8},
    "ShortSlow": {"sf": 9, "bw": 250, "cr": 5, "preamble": 8},
    "ShortFast": {"sf": 8, "bw": 250, "cr": 5, "preamble": 8},
    "MediumSlow": {"sf": 10, "bw": 250, "cr": 5, "preamble": 8},
    "MediumFast": {"sf": 9, "bw": 250, "cr": 5, "preamble": 8},
    "LongSlow": {"sf": 12, "bw": 250, "cr": 5, "preamble": 8},
    "LongFast": {"sf": 11, "bw": 250, "cr": 5, "preamble": 8},
    "LongMod": {"sf": 11, "bw": 250, "cr": 6, "preamble": 8},
    "VLongSlow": {"sf": 12, "bw": 125, "cr": 5, "preamble": 8},
}

SYNC_WORD_MESHTASTIC = "0x2B"

# Primary/default channel frequency for each region's Meshtastic LongFast-style
# hop table. 906.875 MHz is the US915 default already used by ``sniff lora
# scan`` and ``meshtastic live`` elsewhere in this CLI; 869.525 MHz is the
# commonly used EU868 default channel. A real mesh may hash to a different
# channel — ``-freq`` still overrides this if so.
_MESHTASTIC_REGION_FREQUENCIES_HZ = {
    "us915": 906_875_000,
    "eu868": 869_525_000,
}

LORA_PROFILE_KEYS = {
    "frequency",
    "bandwidth",
    "spread_factor",
    "coding_rate",
    "tx_power",
    "sync_word",
    "preamble",
    "iq",
}
FSK_PROFILE_KEYS = {
    "frequency",
    "bitrate",
    "fdev",
    "bandwidth",
    "tx_power",
    "preamble",
    "sync_word",
    "bt",
    "crc",
    "whitening",
    "pktlen",
    "payload",
}
PROFILE_KEYS_BY_COMMAND = {"lora": LORA_PROFILE_KEYS, "fsk": FSK_PROFILE_KEYS}


def _builtin_profiles() -> Dict[str, dict]:
    profiles = {}
    for region, freq_hz in _MESHTASTIC_REGION_FREQUENCIES_HZ.items():
        for preset_name, cfg in MESHTASTIC_CHANNEL_PRESETS.items():
            name = f"{region}-meshtastic-{preset_name.lower()}"
            profiles[name] = {
                "command": "lora",
                "frequency": freq_hz,
                "bandwidth": str(cfg["bw"]),
                "spread_factor": cfg["sf"],
                "coding_rate": cfg["cr"],
                "preamble": cfg["preamble"],
                "sync_word": SYNC_WORD_MESHTASTIC,
            }
    return profiles


def _profiles_path(path: Optional[str] = None) -> Path:
    if path is not None:
        return Path(path)
    env_path = os.environ.get(PROFILES_ENV_VAR)
    if env_path:
        return Path(env_path)
    return DEFAULT_PROFILES_PATH


def _load_user_profiles(path: Optional[str] = None) -> Dict[str, dict]:
    """Parse ``[profiles.NAME]`` tables out of the user's TOML file.

    A missing file is normal (most users never create one) and returns no
    profiles; a file that exists but fails to parse is not — that is a typo
    the user needs to see, not a silent fallback to built-ins only.
    """
    profiles_path = _profiles_path(path)
    if not profiles_path.is_file():
        return {}

    try:
        with open(profiles_path, "rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"{profiles_path}: invalid TOML: {exc}")

    raw_profiles = data.get("profiles", {})
    if not isinstance(raw_profiles, dict):
        raise ProfileError(f"{profiles_path}: [profiles] must be a table of tables")

    profiles = {}
    for name, fields in raw_profiles.items():
        if not isinstance(fields, dict):
            raise ProfileError(
                f"{profiles_path}: profiles.{name} must be a table, e.g. "
                f"[profiles.{name}]"
            )
        profiles[str(name).strip().lower()] = dict(fields)
    return profiles


def available_profiles(path: Optional[str] = None) -> Dict[str, dict]:
    """Built-in profiles plus the user's, the user's winning name collisions."""
    profiles = _builtin_profiles()
    profiles.update(_load_user_profiles(path))
    return profiles


def resolve_profile(
    name: str, expected_command: str, path: Optional[str] = None
) -> Dict[str, object]:
    """Look up ``name`` and return it as Click parameter-name -> value.

    Raises :class:`ProfileError` if the name is unknown, if it was written for
    the other radio mode (a LoRa profile's ``spread_factor``/``preamble``
    mean something different in FSK, and its ``sync_word`` is a different
    shape entirely — applying it there would silently misconfigure the
    radio rather than error), or if it names a field that command doesn't
    have.
    """
    profiles = available_profiles(path)
    key = str(name).strip().lower()

    if key not in profiles:
        available = ", ".join(sorted(profiles)) or "(none)"
        raise ProfileError(
            f"Unknown profile {name!r}. Available: {available}\n"
            f"(user profiles come from {_profiles_path(path)})"
        )

    profile = dict(profiles[key])
    command = str(profile.pop("command", "lora")).strip().lower()
    if command not in PROFILE_KEYS_BY_COMMAND:
        raise ProfileError(
            f"Profile {name!r} has command = {command!r}: must be 'lora' or 'fsk'"
        )
    if command != expected_command:
        raise ProfileError(
            f"Profile {name!r} is a {command} profile — use it with "
            f"'catnip sniff {command}', not 'sniff {expected_command}'"
        )

    allowed = PROFILE_KEYS_BY_COMMAND[command]
    unknown = set(profile) - allowed
    if unknown:
        raise ProfileError(
            f"Profile {name!r} has field(s) not valid for {command}: "
            f"{', '.join(sorted(unknown))}"
        )

    return profile


def describe_profile(profile: Dict[str, object]) -> str:
    """One-line human summary for ``catnip sniff profiles``."""
    command = profile.get("command", "lora")
    if command == "fsk":
        parts = (
            [f"{profile['frequency'] / 1e6:.3f} MHz"] if "frequency" in profile else []
        )
        if "bitrate" in profile:
            parts.append(f"{profile['bitrate']} bps")
        if "fdev" in profile:
            parts.append(f"±{profile['fdev']} Hz")
        if "sync_word" in profile:
            parts.append(f"sync {profile['sync_word']}")
    else:
        parts = (
            [f"{profile['frequency'] / 1e6:.3f} MHz"] if "frequency" in profile else []
        )
        if "bandwidth" in profile:
            parts.append(f"BW{profile['bandwidth']}")
        if "spread_factor" in profile:
            parts.append(f"SF{profile['spread_factor']}")
        if "coding_rate" in profile:
            parts.append(f"CR4/{profile['coding_rate']}")
        if "sync_word" in profile:
            parts.append(f"sync {profile['sync_word']}")
    return ", ".join(parts)
