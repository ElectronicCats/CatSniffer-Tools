import enum

START_OF_FRAME = b"\x40\x53"
END_OF_FRAME = b"\x40\x45"

BYTE_IEEE802145 = b"\x13"
CHANNEL_RANGE_IEEE802145 = [
    (channel, (2405.0 + (5 * (channel - 11)))) for channel in range(11, 27)
]
CONST_FRECUENCY = 65536  # 2^16 -> 16 bits -> MHz


class TIBaseCommand:
    class ByteCommands(enum.Enum):
        PING = 0x40
        START = 0x41
        STOP = 0x42
        PAUSE = 0x43
        RESUME = 0x44
        CFG_FREQUENCY = 0x45
        CFG_PHY = 0x47

    def __init__(self, cmd, data=b"") -> None:
        self.cmd = cmd
        self.data = data
        self.packet = self.__pack()

    def calculate_fcs(self) -> bytes:
        if type(self.cmd) == int:
            self.cmd = self.cmd.to_bytes(1, byteorder="little")
        core_bytes = sum(self.cmd + len(self.data).to_bytes(2, byteorder="little"))
        if self.data != b"":
            core_bytes += sum(self.data)

        checksum = core_bytes & 0xFF
        return checksum.to_bytes(1, byteorder="little")

    def __pack(self):
        if type(self.cmd) == int:
            self.cmd = self.cmd.to_bytes(1, byteorder="little")
        return b"".join(
            [
                START_OF_FRAME,
                self.cmd,
                len(self.data).to_bytes(2, byteorder="little"),
                self.data,
                self.calculate_fcs(),
                END_OF_FRAME,
            ]
        )

    def __str__(self):
        return f"TISnifferPacket.PacketCommand(cmd={self.cmd}, data={self.data}, packet={self.packet})"


class SnifferTI:
    class Commands:
        def __init__(self):
            pass

        def _calculate_frequency(self, frequency) -> bytes:
            integer_value = int(frequency)
            fractional_value = int((integer_value - integer_value) * CONST_FRECUENCY)
            frequency_int_bytes = integer_value.to_bytes(2, byteorder="little")
            frequency_frac_bytes = fractional_value.to_bytes(2, byteorder="little")
            return frequency_int_bytes + frequency_frac_bytes

        def _convert_channel_to_freq(self, channel) -> bytes:
            for _channel in CHANNEL_RANGE_IEEE802145:
                if _channel[0] == channel:
                    return self._calculate_frequency(_channel[1])
            return self._calculate_frequency(CHANNEL_RANGE_IEEE802145[0][1])

        def ping(self) -> bytes:
            return TIBaseCommand(TIBaseCommand.ByteCommands.PING.value)

        def start(self) -> bytes:
            return TIBaseCommand(TIBaseCommand.ByteCommands.START.value)

        def stop(self) -> bytes:
            return TIBaseCommand(TIBaseCommand.ByteCommands.STOP.value)

        def pause(self) -> bytes:
            return TIBaseCommand(TIBaseCommand.ByteCommands.PAUSE.value)

        def resume(self) -> bytes:
            return TIBaseCommand(TIBaseCommand.ByteCommands.RESUME.value)

        def config_freq(self, channel) -> bytes:
            frequency = self._convert_channel_to_freq(channel=channel)
            return TIBaseCommand(
                TIBaseCommand.ByteCommands.CFG_FREQUENCY.value, frequency
            )

        def config_phy(self) -> bytes:
            return TIBaseCommand(
                TIBaseCommand.ByteCommands.CFG_PHY.value, BYTE_IEEE802145
            )

        def get_startup_cmd(self, channel=11):
            startup_cmds = [
                SnifferTI.Commands().ping().packet,
                SnifferTI.Commands().stop().packet,
                SnifferTI.Commands().config_phy().packet,
                SnifferTI.Commands().config_freq(channel=channel).packet,
                SnifferTI.Commands().start().packet,
            ]
            return startup_cmds

    def __init__(self):
        pass
