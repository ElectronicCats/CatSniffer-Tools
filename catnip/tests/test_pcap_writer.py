"""
test_pcap_writer.py
===================
Invariants for ``PcapFileWriter`` (``modules/core/bridge.py``), the file sink
that runs in parallel with the Wireshark named pipe.

The bridges already build one classic-PCAP record per packet and push it into
the pipe, where it is lost when the session ends.  ``PcapFileWriter`` puts the
same records on disk so a capture can be re-opened, run through ``tshark``,
shared, or kept as a regression fixture.

What these tests pin:

- the ``.pcap`` output is *byte-identical* to what the pipe receives, so the
  file sink can never drift away from the live view;
- the ``.pcapng`` output is a spec-shaped section (SHB + IDB + EPB) with the
  timestamps and link type preserved — that one is re-encoded rather than
  copied, so it needs real structural checks;
- an existing capture file is never silently truncated.

The pcapng blocks are parsed back with ``struct`` rather than with Wireshark:
the test suite must not depend on ``tshark`` being installed.  The output of
this writer has been checked against ``tshark``/``capinfos`` by hand.
"""

import struct

import pytest

from modules.core.bridge import PcapFileWriter
from protocol.common import (
    PCAP_MAGIC_NUMBER,
    PCAP_MAX_PACKET_SIZE,
    PCAP_PACKET_HEADER_FORMAT,
    PCAP_PACKET_HEADER_LEN,
    Pcap,
    get_global_header,
)

# ``sniff lora`` writes LoRaTap, ``sniff zigbee|thread`` DLT 147; both are
# exercised so nothing hard-codes one of them.
LORATAP_DLT = 270
TI_DLT = 147

_PCAP_GLOBAL_HEADER_LEN = 24
_PCAPNG_SHB_TYPE = 0x0A0D0D0A
_PCAPNG_IDB_TYPE = 0x00000001
_PCAPNG_EPB_TYPE = 0x00000006


def make_record(payload: bytes, timestamp: float) -> bytes:
    """A record exactly as the bridges hand it to ``pipe.write_packet()``."""
    return Pcap(payload, timestamp).get_pcap()


def iter_blocks(data: bytes):
    """Yield ``(block_type, body)`` for a pcapng byte stream.

    Also asserts the block framing itself: pcapng repeats the total length at
    both ends of every block precisely so a reader can walk backwards, and a
    mismatch there is the failure mode a hand-rolled writer actually has.
    """
    offset = 0
    while offset < len(data):
        block_type, total_length = struct.unpack_from("<II", data, offset)
        assert total_length % 4 == 0, "blocks must stay 4-byte aligned"
        assert offset + total_length <= len(data), "block runs past end of file"
        trailer = struct.unpack_from("<I", data, offset + total_length - 4)[0]
        assert trailer == total_length, "leading/trailing block lengths disagree"
        yield block_type, data[offset + 8 : offset + total_length - 4]
        offset += total_length


def parse_epb(body: bytes):
    """``(timestamp_us, captured_bytes)`` from an Enhanced Packet Block body."""
    interface_id, ts_high, ts_low, caplen, origlen = struct.unpack_from("<IIIII", body)
    assert interface_id == 0, "only one interface is ever declared"
    assert caplen == origlen, "nothing is truncated on the way to disk"
    return (ts_high << 32) | ts_low, body[20 : 20 + caplen]


@pytest.mark.unit
class TestDisabled:
    """``path=None`` is the common case: no ``-w``, so the sink must be inert."""

    def test_no_path_creates_nothing(self, tmp_path):
        writer = PcapFileWriter(None)
        assert writer.enabled is False
        writer.write_record(make_record(b"\x01\x02", 1.0))
        writer.close()
        assert list(tmp_path.iterdir()) == []

    def test_close_is_idempotent(self, tmp_path):
        target = tmp_path / "capture.pcap"
        writer = PcapFileWriter(str(target))
        writer.close()
        writer.close()
        assert writer.enabled is False


@pytest.mark.unit
class TestClassicPcap:
    def test_header_matches_the_one_sent_to_the_pipe(self, tmp_path):
        """Same bytes, same function — the file and the pipe cannot disagree."""
        target = tmp_path / "capture.pcap"
        PcapFileWriter(str(target), LORATAP_DLT).close()
        assert target.read_bytes() == get_global_header(LORATAP_DLT)

    @pytest.mark.parametrize("linktype", [LORATAP_DLT, TI_DLT])
    def test_global_header_declares_the_link_type(self, tmp_path, linktype):
        target = tmp_path / "capture.pcap"
        PcapFileWriter(str(target), linktype).close()
        magic, _, _, _, _, snaplen, declared = struct.unpack(
            "<LHHIILL", target.read_bytes()
        )
        assert magic == PCAP_MAGIC_NUMBER
        assert snaplen == PCAP_MAX_PACKET_SIZE
        assert declared == linktype

    def test_records_are_written_through_untouched(self, tmp_path):
        target = tmp_path / "capture.pcap"
        records = [
            make_record(f"packet {i}".encode(), 1700000000.5 + i) for i in range(3)
        ]

        writer = PcapFileWriter(str(target), LORATAP_DLT)
        for record in records:
            writer.write_record(record)
        writer.close()

        expected = get_global_header(LORATAP_DLT) + b"".join(records)
        assert target.read_bytes() == expected

    def test_each_record_is_flushed_as_it_arrives(self, tmp_path):
        """A capture must be readable while it is still running (tail, tshark -i)."""
        target = tmp_path / "capture.pcap"
        writer = PcapFileWriter(str(target), LORATAP_DLT)
        writer.write_record(make_record(b"live", 1700000000.0))
        assert len(target.read_bytes()) > _PCAP_GLOBAL_HEADER_LEN
        writer.close()

    def test_packet_count_tracks_records(self, tmp_path):
        writer = PcapFileWriter(str(tmp_path / "capture.pcap"), LORATAP_DLT)
        for i in range(4):
            writer.write_record(make_record(b"x", 1700000000.0 + i))
        assert writer.packet_count == 4
        writer.close()


@pytest.mark.unit
class TestPcapng:
    """The pcapng path re-encodes, so it gets structural checks."""

    def test_suffix_selects_the_format(self, tmp_path):
        assert PcapFileWriter(str(tmp_path / "a.pcapng")).pcapng is True
        assert PcapFileWriter(str(tmp_path / "b.PcapNG")).pcapng is True
        assert PcapFileWriter(str(tmp_path / "c.pcap")).pcapng is False
        assert PcapFileWriter(str(tmp_path / "d.cap")).pcapng is False

    def test_section_starts_with_shb_and_idb(self, tmp_path):
        target = tmp_path / "capture.pcapng"
        PcapFileWriter(str(target), TI_DLT).close()

        blocks = list(iter_blocks(target.read_bytes()))
        assert [block_type for block_type, _ in blocks] == [
            _PCAPNG_SHB_TYPE,
            _PCAPNG_IDB_TYPE,
        ]

        byte_order_magic, major, minor = struct.unpack_from("<IHH", blocks[0][1])
        assert byte_order_magic == 0x1A2B3C4D
        assert (major, minor) == (1, 0)

        linktype, _, snaplen = struct.unpack_from("<HHI", blocks[1][1])
        assert linktype == TI_DLT
        assert snaplen == PCAP_MAX_PACKET_SIZE

    def test_packets_become_epbs_with_the_same_payload_and_timestamp(self, tmp_path):
        target = tmp_path / "capture.pcapng"
        payloads = [b"first", b"second", b"third"]
        timestamps = [1700000000.125, 1700000001.5, 1700000002.75]

        writer = PcapFileWriter(str(target), LORATAP_DLT)
        for payload, timestamp in zip(payloads, timestamps):
            writer.write_record(make_record(payload, timestamp))
        writer.close()

        epbs = [
            parse_epb(body)
            for block_type, body in iter_blocks(target.read_bytes())
            if block_type == _PCAPNG_EPB_TYPE
        ]
        assert [payload for _, payload in epbs] == payloads
        # The record header stores whole seconds plus microseconds, so compare
        # against that rounding rather than against the float we started from.
        for (timestamp_us, _), source in zip(epbs, timestamps):
            seconds = int(source)
            expected = seconds * 1_000_000 + int((source - seconds) * 1_000_000)
            assert timestamp_us == expected

    @pytest.mark.parametrize("length", [1, 2, 3, 4, 5, 7, 8])
    def test_odd_length_payloads_stay_aligned(self, tmp_path, length):
        """Unpadded packet data is the classic way a pcapng writer corrupts a file."""
        target = tmp_path / "capture.pcapng"
        writer = PcapFileWriter(str(target), LORATAP_DLT)
        writer.write_record(make_record(b"\xab" * length, 1700000000.0))
        writer.write_record(make_record(b"after", 1700000001.0))
        writer.close()

        # iter_blocks asserts the framing; getting through both EPBs is the check.
        payloads = [
            parse_epb(body)[1]
            for block_type, body in iter_blocks(target.read_bytes())
            if block_type == _PCAPNG_EPB_TYPE
        ]
        assert payloads == [b"\xab" * length, b"after"]

    def test_records_the_writing_application(self, tmp_path):
        """``capinfos`` reports this; it is how a shared capture names its source."""
        target = tmp_path / "capture.pcapng"
        PcapFileWriter(str(target), LORATAP_DLT).close()
        assert b"catnip" in target.read_bytes()


@pytest.mark.unit
class TestOverwriteGuard:
    """``--raw``/``--ascii`` append; a capture file is truncated, so it must ask."""

    def test_existing_file_blocks_the_capture(self, tmp_path):
        target = tmp_path / "capture.pcap"
        target.write_bytes(b"previous capture")

        with pytest.raises(FileExistsError):
            PcapFileWriter(str(target), LORATAP_DLT)
        assert target.read_bytes() == b"previous capture"

    def test_force_truncates(self, tmp_path):
        target = tmp_path / "capture.pcap"
        target.write_bytes(b"previous capture")

        PcapFileWriter(str(target), LORATAP_DLT, force=True).close()
        assert target.read_bytes() == get_global_header(LORATAP_DLT)


@pytest.mark.unit
class TestWriteFailures:
    def test_a_failing_write_disables_the_sink_instead_of_killing_the_capture(
        self, tmp_path
    ):
        """A full disk should cost the file, not the live session."""
        target = tmp_path / "capture.pcap"
        writer = PcapFileWriter(str(target), LORATAP_DLT)

        class _BrokenFile:
            def write(self, _data):
                raise OSError("No space left on device")

            def flush(self):
                pass

            def close(self):
                pass

        writer.fh = _BrokenFile()
        writer.write_record(make_record(b"lost", 1700000000.0))

        assert writer.enabled is False
        assert writer.packet_count == 0
        # Still a no-op afterwards rather than a second failure.
        writer.write_record(make_record(b"also lost", 1700000001.0))

    def test_a_truncated_record_does_not_propagate(self, tmp_path):
        """Defensive: a short record would raise inside struct.unpack_from."""
        target = tmp_path / "capture.pcapng"
        writer = PcapFileWriter(str(target), LORATAP_DLT)
        writer.write_record(b"\x00\x01\x02")
        assert writer.enabled is False


@pytest.mark.unit
def test_record_header_length_matches_the_shared_format():
    """The pcapng path slices packet data at this offset; keep them in step."""
    assert PCAP_PACKET_HEADER_LEN == struct.calcsize(PCAP_PACKET_HEADER_FORMAT)
    assert PCAP_PACKET_HEADER_LEN == 16
