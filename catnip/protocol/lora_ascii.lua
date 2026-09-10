-- Renders the LoRa payload as text, for the ASCII column catnip adds to
-- Wireshark (see ``lora_wireshark_display_args`` in sniffer_sx.py).
--
-- LoRaTap carries the payload as bytes, and Wireshark renders a bytes field as
-- hex, so a text payload -- most of what a LoRa bench sends -- can only be read
-- by clicking into a packet and squinting at the hex pane.  A postdissector
-- runs after the LoRaTap dissector, so it can pick `loratap.payload` back up
-- and register the same bytes a second time as a string field, whichever
-- dissector `--dissect-as` gave the payload to.

local catnip_lora = Proto("catnip_lora", "CatSniffer LoRa")
local ascii_field = ProtoField.string("catnip_lora.ascii", "Payload (ASCII)")
catnip_lora.fields = { ascii_field }

local lora_payload = Field.new("loratap.payload")

-- Anything outside printable 7-bit ASCII becomes ".", the convention every hex
-- dump already uses, so one packet stays one line whatever the radio heard.
local function to_ascii(bytes)
    local out = {}
    for i = 0, bytes:len() - 1 do
        local byte = bytes:get_index(i)
        out[i + 1] = (byte >= 0x20 and byte <= 0x7E) and string.char(byte) or "."
    end
    return table.concat(out)
end

function catnip_lora.dissector(tvb, pinfo, tree)
    local payload = lora_payload()
    if not payload then
        return
    end

    local range = payload.range
    if range:len() == 0 then
        return
    end

    tree:add(catnip_lora, range):add(ascii_field, range, to_ascii(range:bytes()))
end

register_postdissector(catnip_lora)
