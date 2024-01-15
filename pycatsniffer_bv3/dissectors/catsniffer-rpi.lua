--[[
    This dissector is for the TI radio Packet Info Header which includes meta information
    and is mean to be used with the TiWsPc2 packet sniffer software from TI
]]

UDP_PORT_DISSECTOR = 17760
FRACT_CONSTANT     = 65535
STATUS_OK          = 0x80
TI_RPI_MIN_LENGTH  = 17

INTERFACE_TYPE_COM   = 0
INTERFACE_TYPE_CEBAL = 1

--  /* PHY type values */
PHY_TYPE_UNUSED                  = 0
PHY_TYPE_50KBPS_GFSK             = 1
PHY_TYPE_SLR                     = 2
PHY_TYPE_OQPSK                   = 3
PHY_TYPE_200KBPS_GFSK            = 4
PHY_TYPE_BLE                     = 5
PHY_TYPE_WBMS                    = 6
PHY_TYPE_50KBPS_GFSK_WISUN_1A    = 7
PHY_TYPE_50KBPS_GFSK_WISUN_1B    = 8
PHY_TYPE_100KBPS_GFSK_WISUN_2A   = 9
PHY_TYPE_100KBPS_GFSK_WISUN_2B   = 10
PHY_TYPE_150KBPS_GFSK_WISUN_3    = 11
PHY_TYPE_200KBPS_GFSK_WISUN_4A   = 12
PHY_TYPE_200KBPS_GFSK_WISUN_4B   = 13
PHY_TYPE_100KBPS_GFSK_ZIGBEE_R23 = 14
PHY_TYPE_500KBPS_GFSK_ZIGBEE_R23 = 15

PHY_50KBPS_GFSK_STRING             = "50 Kbps GFSK"
PHY_SLR_STRING                     = "SLR"
PHY_OQPSK_STRING                   = "O-QPSK"
PHY_200KBPS_GFSK_STRING            = "200 Kbps GFSK"
PHY_BLE_STRING                     = "BLE 1 Mbps"
PHY_WBMS_STRING                    = "WBMS 2 Mbps"
PHY_50KBPS_GFSK_WISUN_1A_STRING    = "50 Kbps GFSK (Wi-SUN mode 1a)"
PHY_50KBPS_GFSK_WISUN_1B_STRING    = "50 Kbps GFSK (Wi-SUN mode 1b)"
PHY_100KBPS_GFSK_WISUN_2A_STRING   = "100 Kbps GFSK (Wi-SUN mode 2a)"
PHY_100KBPS_GFSK_WISUN_2B_STRING   = "100 Kbps GFSK (Wi-SUN mode 2b)"
PHY_150KBPS_GFSK_WISUN_3_STRING    = "150 Kbps GFSK (Wi-SUN mode 3)"
PHY_200KBPS_GFSK_WISUN_4A_STRING   = "200 Kbps GFSK (Wi-SUN mode 4a)"
PHY_200KBPS_GFSK_WISUN_4B_STRING   = "200 Kbps GFSK (Wi-SUN mode 4b)"
PHY_100KBPS_GFSK_ZIGBEE_R23_STRING = "100 Kbps GFSK (ZigBee R23)"
PHY_500KBPS_GFSK_ZIGBEE_R23_STRING = "500 Kbps GFSK (ZigBee R23)"

--  /* Protocol values */
PROTOCOL_GENERIC         = 0
PROTOCOL_IEEE_802_15_4_G = 1
PROTOCOL_IEEE_802_15_4   = 2
PROTOCOL_BLE             = 3
PROTOCOL_WBMS            = 4

--  /* Header field offset values */
INTERFACE_TYPE_OFFSET       = 3
INTERFACE_ID_OFFSET         = 4
PROTOCOL_OFFSET             = 6
PHY_OFFSET                  = 7
FREQUENCY_OFFSET            = 8
FRACTIONAL_FREQUENCY_OFFSET = 10
CHANNEL_OFFSET              = 12
RSSI_OFFSET                 = 14
STATUS_OFFSET               = 15
PAYLOAD_OFFSET              = 16


--  /* Header field size values */
INTERFACE_ID_SIZE = 2
PHY_SIZE          = 1
FREQUENCY_SIZE    = 4     --  /* Size of frequency + fractional frequency values in total */
CHANNEL_SIZE      = 2
RSSI_SIZE         = 1
STATUS_SIZE       = 1


function build_catsniffer_rpi_p()
    catsniffer_rpi_p = Proto("catsniffer_rpi", "CatSniffer Radio Packet Info")

    local cs_interface_id   = ProtoField.string("catsniffer.interface", "Interface", base.NONE)
    local cs_frequency      = ProtoField.float("catsniffer.freq", "Frequency", base.NONE)
    local cs_channel        = ProtoField.uint16("catsniffer.channel", "Channel", base.DEC)
    local cs_phy_protocol   = ProtoField.string("catsniffer.phy", "PHY", base.NONE)
    local cs_rssi           = ProtoField.int8("catsniffer.rssi", "RSSI", base.DEC)
    local cs_status         = ProtoField.uint8("catsniffer.fcs", "Frame Check Status", base.HEX)
    local cs_payload_length = ProtoField.string("catsniffer.length", "Payload Length", base.NONE)

    catsniffer_rpi_p.fields = { 
        cs_interface_id,
        cs_frequency,
        cs_channel,
        cs_phy_protocol,
        cs_rssi,
        cs_status,
        cs_payload_length
    }

    function catsniffer_rpi_p.dissector(tvbuf, pktinfo, root)
        if tvbuf:len() < TI_RPI_MIN_LENGTH then
            return 0
        end
    
        local freq, fractFrq, fullFreq, protocol, chanell, phy, rssi, status, payload_length
    
        pktinfo.cols.info = "CatSniffer Low Energy Data"

        -- Add CatSniffer Protocol as sub root in the wireshark display
        local subtree_radio_packet = root:add(catsniffer_rpi_p, tvbuf(), "CatSniffer Radio Packet Info")
    
        -- Display interface information
        interface_subtree = subtree_radio_packet:add_le(cs_interface_id, "COM " .. tvbuf(INTERFACE_ID_OFFSET, INTERFACE_ID_SIZE):le_uint())
    
        -- Display frequency and fractional frequency in MHz
        freq =  tvbuf(FREQUENCY_OFFSET, FREQUENCY_SIZE):le_uint()
        fractFrq = tvbuf(FRACTIONAL_FREQUENCY_OFFSET, FREQUENCY_SIZE):float()
        fullFreq = freq + (fractFrq/FRACT_CONSTANT)
    
        subtree_radio_packet:add_le(cs_frequency, fullFreq):append_text(" MHz")
    
        -- Find value of protocol field to set the channell
        protocol = tvbuf(PROTOCOL_OFFSET,1):le_uint()
        
        if protocol ~= PROTOCOL_GENERIC then
            chanell = tvbuf(CHANNEL_OFFSET, CHANNEL_SIZE):le_uint()
            subtree_radio_packet:add_le(cs_channel, chanell)
        end
    
        -- Display the PHY type for known values
        phy = tvbuf(PHY_OFFSET, 1):le_uint()
        if protocol == PROTOCOL_BLE and phy == PHY_TYPE_BLE then
            subtree_radio_packet:add_le(cs_phy_protocol, PHY_BLE_STRING)
        end
    
        -- Display RSSI
        rssi = tvbuf(RSSI_OFFSET, RSSI_SIZE)
        subtree_radio_packet:add_le(cs_rssi, rssi):append_text(" dBm")
    
        -- Display Status
        status = tvbuf(STATUS_OFFSET, STATUS_SIZE):le_uint()
        status_subtree = subtree_radio_packet:add_le(cs_status, status)
        if status == STATUS_OK then
            status_subtree:append_text(" - OK")
        else
            status_subtree:append_text(" - BAD FCS")
        end
    
        -- Display Payload Length
        payload_length = tvbuf:reported_len() - PAYLOAD_OFFSET
        subtree_radio_packet:add_le(cs_payload_length, payload_length):append_text(" Bytes")
    
        -- Foward the packet to the BLE dissector
        local payloadTvb = tvbuf(PAYLOAD_OFFSET):tvb()
        --if protocol == PROTOCOL_BLE then
            
        --end
        local ble_dissector = Dissector.get("catsniffer_blepi")
        ble_dissector:call(payloadTvb, pktinfo, root)
        
        local dissector = Dissector.get("btle")
        dissector:call(payloadTvb, pktinfo, root)
        return tvbuf:captured_len()
    end
    return catsniffer_rpi_p
end
--local udp_port = DissectorTable.get("udp.port")
--udp_port:add(UDP_PORT_DISSECTOR, catsniffer_rpi_p)
--local udp_port = DissectorTable.get("bluetooth.encap")
--udp_port:add(161, catsniffer_rpi_p)
