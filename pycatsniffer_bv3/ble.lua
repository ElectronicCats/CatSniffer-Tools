catsniffer_protocol = Proto("btle", "Catsniffer")

catsniffer_protocol.fields = {}

function catsniffer_protocol.dissector(buffer, pinfo, tree)
	length = buffer:len()
	if length == 0 then
		return
	end

	pinfo.cols.protocol = catsniffer_protocol.name

	local subtree = tree:add(catsniffer_protocol, buffer(), "Catsniffer Energy Data")
end

local ble_dissector_table = DissectorTable.get("bluetooth.src")
ble_dissector_table(add_port, catsniffer_protocol)
