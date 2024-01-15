--[[
    This dissector is for the TI radio Packet Info Header which includes meta information
    and is mean to be used with the TiWsPc2 packet sniffer software from TI
]]

UDP_PORT_DISSECTOR = 17760
FRACT_CONSTANT     = 65535

-- Minimum length (in bytes) of the protocol data.
BLEPI_MIN_LENGTH  = 4
-- Header field offset values
CONN_EVENT_OFFSET = 0
INFO_OFFSET       = 2
PAYLOAD_OFFSET    = 3
-- Header field size values
CONN_EVENT_SIZE   = 2
INFO_SIZE         = 1

-- Value and string pairs for the direction info field
DIRECTION_VALUE_STRING = {
    [0x00] = "Not Connected",
    [0x01] = "Master -> Slave",
    [0x02] = "Slave -> Master",
    [0x03] = "Unknown Direction",
    [0] = nil
}

function build_catsniffer_blepi_p()

    catsniffer_blepi_p = Proto("catsniffer_blepi", "CatSniffer BLE Packet Info")

    local cs_connection_evt = ProtoField.uint16("catsniffer.conn_event", "Connection Event", base.DEC)
    local cs_info           = ProtoField.uint8("catsniffer.info", "Info", base.HEX)
    local cs_direction      = ProtoField.uint8("catsniffer.direction", "Direction", base.HEX, DIRECTION_VALUE_STRING)

    catsniffer_blepi_p.fields = { 
        cs_connection_evt,
        cs_info,
        cs_direction
    }

    function catsniffer_blepi_p.dissector(tvbuf, pkinfo, tree, _u_)
        if tvbuf:len() < BLEPI_MIN_LENGTH then
            return 0
        end

        -- Add CatSniffer Protocol as sub tree in the wireshark display
        local subtree_radio_packet = tree:add(catsniffer_blepi_p, tvbuf)

        -- Connection Event
        local connection_event = tvbuf(CONN_EVENT_OFFSET, CONN_EVENT_SIZE):le_uint()
        subtree_radio_packet:add_le(cs_connection_evt, connection_event)

        -- Info
        local info = tvbuf(INFO_OFFSET, INFO_SIZE):le_uint()
        subtree_radio_packet:add_le(cs_info, info)
        local info_tree = subtree_radio_packet:add(cs_direction, info)
        info_tree:add(cs_direction, tvbuf(INFO_OFFSET, INFO_SIZE):uint())

        -- Foward paload to BLE (btle) dissector
        -- local dissector = Dissector.get("btle")
        -- dissector:call(tvbuf(PAYLOAD_OFFSET):tvb(), pkinfo, tree)
        
    end
    return catsniffer_blepi_p
end


--local udp_port = DissectorTable.get("udp.port")
--udp_port:add(UDP_PORT_DISSECTOR, catsniffer_protocol_ble)
--local udp_port = DissectorTable.get("bluetooth.encap")
--udp_port:add(161, catsniffer_protocol)
