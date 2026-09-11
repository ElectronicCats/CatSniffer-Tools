"""
test_radio_profiles.py
=======================
Behaviour of ``modules/radio/profiles.py`` -- the built-in region/protocol
presets ``sniff lora|fsk --profile`` draws on, plus the user's own in
``~/.config/catnip/profiles.toml``.

These are pure-function tests: no device, no Click invocation (that lives in
``tests/test_cli_sniff.py``), just the profile registry and its validation.
"""

import pytest

from modules.radio.profiles import (
    LORA_PROFILE_KEYS,
    FSK_PROFILE_KEYS,
    ProfileError,
    available_profiles,
    describe_profile,
    resolve_profile,
)


class TestBuiltinProfiles:
    def test_the_readme_example_resolves(self):
        """The exact profile the feature was asked for."""
        profile = resolve_profile("eu868-meshtastic-longfast", "lora")
        assert profile["frequency"] == 869_525_000
        assert profile["bandwidth"] == "250"
        assert profile["spread_factor"] == 11
        assert profile["coding_rate"] == 5
        assert profile["sync_word"] == "0x2B"

    def test_every_meshtastic_channel_preset_is_covered_for_both_regions(self):
        names = available_profiles()
        for region in ("us915", "eu868"):
            for preset in (
                "longfast",
                "longslow",
                "longmod",
                "mediumfast",
                "mediumslow",
                "shortfast",
                "shortslow",
                "shortturbo",
                "vlongslow",
                "defcon33",
            ):
                assert f"{region}-meshtastic-{preset}" in names

    def test_lookup_is_case_insensitive(self):
        mixed_case = resolve_profile("EU868-Meshtastic-LongFast", "lora")
        lower_case = resolve_profile("eu868-meshtastic-longfast", "lora")
        assert mixed_case == lower_case

    def test_bandwidth_is_a_string_matching_the_cli_choice(self):
        # ``sniff lora``'s -bw is a click.Choice(["125", "250", "500"]); an int
        # here would fail Click's own validation with no explanation pointing
        # back at the profile.
        for name, profile in available_profiles().items():
            if profile.get("command", "lora") == "lora" and "bandwidth" in profile:
                assert isinstance(profile["bandwidth"], str), name

    def test_only_known_lora_fields_are_ever_produced(self):
        for name, profile in available_profiles().items():
            if profile.get("command", "lora") != "lora":
                continue
            fields = set(profile) - {"command"}
            assert fields <= LORA_PROFILE_KEYS, name


class TestProfileNotFound:
    def test_unknown_profile_lists_what_is_available(self):
        with pytest.raises(ProfileError, match="Unknown profile 'nope'"):
            resolve_profile("nope", "lora")

    def test_unknown_profile_message_names_the_user_file(self):
        with pytest.raises(ProfileError, match="profiles.toml"):
            resolve_profile("nope", "lora")


class TestCommandMismatchIsRejected:
    """A LoRa profile's fields mean something else entirely in FSK mode (or
    nothing at all), so applying one under the other command has to be a
    loud error rather than a handful of ignored keys.
    """

    def test_a_lora_profile_is_refused_under_sniff_fsk(self):
        with pytest.raises(ProfileError, match="lora profile"):
            resolve_profile("eu868-meshtastic-longfast", "fsk")

    def test_the_error_names_the_right_command_to_use_instead(self):
        with pytest.raises(ProfileError, match="catnip sniff lora"):
            resolve_profile("eu868-meshtastic-longfast", "fsk")


class TestUserProfilesFile:
    def _write(self, tmp_path, contents):
        path = tmp_path / "profiles.toml"
        path.write_text(contents)
        return str(path)

    def test_a_missing_file_is_not_an_error(self, tmp_path):
        missing = str(tmp_path / "does-not-exist.toml")
        assert available_profiles(missing) == available_profiles(
            str(tmp_path / "also-missing.toml")
        )

    def test_a_user_profile_is_found_by_name(self, tmp_path):
        path = self._write(
            tmp_path,
            """
            [profiles.home-lora]
            frequency = 915000000
            bandwidth = "125"
            spread_factor = 7
            coding_rate = 5
            sync_word = "private"
            preamble = 12
            """,
        )
        profile = resolve_profile("home-lora", "lora", path=path)
        assert profile["frequency"] == 915000000
        assert profile["sync_word"] == "private"

    def test_a_user_profile_overrides_a_builtin_of_the_same_name(self, tmp_path):
        path = self._write(
            tmp_path,
            """
            [profiles.eu868-meshtastic-longfast]
            frequency = 868100000
            """,
        )
        profile = resolve_profile("eu868-meshtastic-longfast", "lora", path=path)
        assert profile["frequency"] == 868100000
        # Fields the override doesn't mention are simply absent here -- the
        # override *replaces* the built-in profile rather than merging into it.
        assert "bandwidth" not in profile

    def test_an_fsk_profile_declares_its_command(self, tmp_path):
        path = self._write(
            tmp_path,
            """
            [profiles.home-fsk]
            command = "fsk"
            frequency = 868000000
            bitrate = 50000
            fdev = 25000
            sync_word = "2DD4"
            """,
        )
        profile = resolve_profile("home-fsk", "fsk", path=path)
        assert set(profile) - {"command"} <= FSK_PROFILE_KEYS
        assert profile["bitrate"] == 50000

    def test_a_field_not_valid_for_the_command_is_rejected(self, tmp_path):
        path = self._write(
            tmp_path,
            """
            [profiles.typo]
            frequency = 915000000
            spread_factorz = 7
            """,
        )
        with pytest.raises(ProfileError, match="spread_factorz"):
            resolve_profile("typo", "lora", path=path)

    def test_an_invalid_declared_command_is_rejected(self, tmp_path):
        path = self._write(
            tmp_path,
            """
            [profiles.bogus]
            command = "zigbee"
            """,
        )
        with pytest.raises(ProfileError, match="must be 'lora' or 'fsk'"):
            resolve_profile("bogus", "lora", path=path)

    def test_malformed_toml_is_reported_with_the_file_path(self, tmp_path):
        path = self._write(tmp_path, "this is not valid toml [[[")
        with pytest.raises(ProfileError, match="invalid TOML"):
            available_profiles(path)

    def test_a_profile_entry_that_is_not_a_table_is_rejected(self, tmp_path):
        path = self._write(tmp_path, "[profiles]\nnot-a-table = 42\n")
        with pytest.raises(ProfileError, match="must be a table"):
            available_profiles(path)


class TestDescribeProfile:
    def test_lora_summary_mentions_the_frequency_and_spreading_factor(self):
        profile = resolve_profile("us915-meshtastic-longfast", "lora")
        profile["command"] = "lora"
        summary = describe_profile(profile)
        assert "906.875 MHz" in summary
        assert "SF11" in summary

    def test_fsk_summary_mentions_the_bitrate(self):
        summary = describe_profile(
            {
                "command": "fsk",
                "frequency": 868_000_000,
                "bitrate": 50000,
                "sync_word": "2DD4",
            }
        )
        assert "50000 bps" in summary
