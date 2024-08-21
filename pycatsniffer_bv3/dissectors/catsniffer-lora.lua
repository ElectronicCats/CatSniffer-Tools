require("catsniffer-blepi")
require("catsniffer-rpi")

VERSION_RELEASE = "1.0.0"
DTL0_LINKLAYER  = 148

UDP_PORT_DISSECTOR = 17760
FRACT_CONSTANT     = 65535
STATUS_OK          = 0x80
TI_RPI_MIN_LENGTH  = 17

INTERFACE_TYPE_COM   = 0
INTERFACE_TYPE_CEBAL = 1
PHY_TYPE_LORA        = 6
PHY_LORA_STRING      = "LoRa"

--  /* Protocol values */
PROTOCOL_LORA            = 5


--  /* Header field size values */
INTERFACE_ID_SIZE = 2
PHY_SIZE          = 1
FREQUENCY_SIZE    = 4     --  /* Size of frequency + fractional frequency values in total */
CHANNEL_SIZE      = 2
RSSI_SIZE         = 1
STATUS_SIZE       = 1

--  /* Header field offset values */
INTERFACE_TYPE_OFFSET       = 3
INTERFACE_ID_OFFSET         = 4
PROTOCOL_OFFSET             = INTERFACE_ID_OFFSET + INTERFACE_ID_SIZE -- 6
PHY_OFFSET                  = PROTOCOL_OFFSET + PHY_SIZE -- 7
FREQUENCY_OFFSET            = 8
FRACTIONAL_FREQUENCY_OFFSET = 10
CHANNEL_OFFSET              = 12
RSSI_OFFSET                 = 14
STATUS_OFFSET               = 15
PAYLOAD_OFFSET              = 16




function build_catsniffer_rpi_lora()
    catsniffer_rpi_lora_p = Proto("catsniffer_rpi_lora", "CatSniffer LoRa Radio Packet Info")

    local cs_version        = ProtoField.string("catsniffer.version", "Version", base.NONE)
    local cs_interface_id   = ProtoField.string("catsniffer.interface", "Interface", base.NONE)
    local cs_phy_protocol   = ProtoField.string("catsniffer.phy", "PHY", base.NONE)
    local cs_frequency      = ProtoField.float("catsniffer.freq", "Frequency", base.NONE)
    local cs_channel        = ProtoField.uint16("catsniffer.channel", "Channel", base.DEC)
    local cs_rssi           = ProtoField.int32("catsniffer.rssi", "RSSI", base.DEC)
    local cs_payload_length = ProtoField.int32("catsniffer.length", "Payload Length", base.DEC)
    local cs_payload_data   = ProtoField.bytes("catsniffer.payload", "Payload")

    catsniffer_rpi_lora_p.fields = {
        cs_version,
        cs_interface_id,
        cs_phy_protocol,
        cs_frequency,
        cs_channel,
        cs_rssi,
        -- cs_snr,
        cs_payload_length,
        cs_payload_data
    }

    function catsniffer_rpi_lora_p.dissector(tvbuf, pktinfo, root)
        if tvbuf:len() < TI_RPI_MIN_LENGTH then
            return 0
        end

        local freq, fractFrq, fullFreq, protocol, chanell, phy, rssi, status, payload_length

        pktinfo.cols.info     = "Broadcast"
        pktinfo.cols.src   = "CatSniffer"
        pktinfo.cols.protocol = PHY_LORA_STRING

        -- Add CatSniffer Protocol as sub root in the wireshark display
        local subtree_radio_packet = root:add(catsniffer_rpi_lora_p, tvbuf(), "CatSniffer Radio Packet Info")

        interface_subtree = subtree_radio_packet:add_le(cs_version, VERSION_RELEASE)

        -- Display interface information
        interface_subtree = subtree_radio_packet:add_le(cs_interface_id, "COM " .. tvbuf(INTERFACE_ID_OFFSET, INTERFACE_ID_SIZE):le_uint())

         -- Display the PHY type for known values
         phy = tvbuf(PHY_OFFSET, PHY_SIZE):le_uint()
         subtree_radio_packet:add_le(cs_phy_protocol, PHY_LORA_STRING)

        -- Display frequency and fractional frequency in MHz
        freq =  tvbuf(FREQUENCY_OFFSET, FREQUENCY_SIZE):le_uint()
        fractFrq = tvbuf(FRACTIONAL_FREQUENCY_OFFSET, FREQUENCY_SIZE):float()
        fullFreq = freq + (fractFrq/FRACT_CONSTANT)

        subtree_radio_packet:add(cs_frequency, fullFreq):append_text(" MHz")

        -- Find value of protocol field to set the channell
        chanel = tvbuf(CHANNEL_OFFSET, CHANNEL_SIZE)
        subtree_radio_packet:add(cs_channel, chanel)

        -- Display RSSI
        rssi = tvbuf(RSSI_OFFSET, RSSI_SIZE)
        subtree_radio_packet:add_le(cs_rssi, rssi):append_text(" dBm")

        -- Foward the packet to the BLE dissector
        local payloadTvb = tvbuf(PAYLOAD_OFFSET) -- :tvb()
        local subtree_data_packet = root:add(catsniffer_rpi_lora_p, payloadTvb, "LoRa Data")
        -- Display Payload Length
        payload_length = tvbuf:reported_len() - PAYLOAD_OFFSET
        subtree_data_packet:add(cs_payload_length, payload_length):set_generated(true):append_text(" Bytes")

        subtree_data_packet:add(cs_payload_data, payloadTvb)

        return tvbuf:captured_len()
    end
    return catsniffer_rpi_lora_p
end


local catsniffer_rpi_lora_p = build_catsniffer_rpi_lora()

-- For User DLT to controll the information of all the CatSniffer packets
local user_dtls = DissectorTable.get("dtls.port")
user_dtls:add(DTL0_LINKLAYER, catsniffer_rpi_lora_p)