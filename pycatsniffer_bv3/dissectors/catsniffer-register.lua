--
-- CatSniffer BLE Dissector
-- Electronic Cats - PwnLab
--
require("catsniffer-blepi")
require("catsniffer-rpi")

-------------------------------------------------------------------------------
-------------------------   Register All Dissectors   -------------------------
-------------------------------------------------------------------------------
--  ----------------------------------------------------------------------------------------------------------------------
--  | Version | Length | Interface Type | Interface ID | Protocol | PHY | Frequency | Channel | RSSI | Status | Payload  |
--  | 1B      | 2B     | 1B             | 2B           | 1B       | 1B  | 4B        | 2B      | 1B   | 1B     | Variable |
--  ----------------------------------------------------------------------------------------------------------------------
-- The format of the BLE meta header is shown below. 
--
-- The variable length payload is forwarded to the Wireshark BLE dissector (btle). 
--  -----------------------------------------------------
--  | Connection Event Counter | Info | Payload         |
--  | 2B                       | 1B   | Variable Length |
--  -----------------------------------------------------

local catsniffer_blepi_p = build_catsniffer_blepi_p()
local catsniffer_rpi_p = build_catsniffer_rpi_p()


local udp_port = DissectorTable.get("udp.port")
udp_port:add(UDP_PORT_DISSECTOR, catsniffer_rpi_p)
local udp_port = DissectorTable.get("bluetooth.encap")
udp_port:add(161, catsniffer_rpi_p)
udp_port:add(156, catsniffer_rpi_p)
udp_port:add(154, catsniffer_rpi_p)