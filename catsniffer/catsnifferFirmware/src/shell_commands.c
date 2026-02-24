/*
 * shell_commands.c - Command Table Based Shell
 */

#include "shell_commands.h"
#include <errno.h>
#include <pico/bootrom.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <zephyr/kernel.h>

#include "catsniffer.h"
#include "fw_metadata.h"

// External functions from main.c
void shell_reply(const char *msg);
void change_mode(unsigned long new_mode);
void change_band(unsigned long new_band);
void process_lora_command(char *cmd_line);
void set_status_leds(int l0, int l1, int l2);

extern catsniffer_t catsniffer;

// Command handler type
typedef void (*cmd_handler_t)(char *args);

// Command table entry
typedef struct {
	const char *name;
	cmd_handler_t handler;
	const char *help;
	bool prefix_match; // true for commands with args (TX, TEST)
} shell_cmd_t;

// Forward declarations
static void cmd_help(char *args);
static void cmd_boot(char *args);
static void cmd_exit(char *args);
static void cmd_band1(char *args);
static void cmd_band2(char *args);
static void cmd_band3(char *args);
static void cmd_reboot(char *args);
static void cmd_status(char *args);
static void cmd_lora_freq(char *args);
static void cmd_lora_sf(char *args);
static void cmd_lora_bw(char *args);
static void cmd_lora_cr(char *args);
static void cmd_lora_power(char *args);
static void cmd_lora_mode(char *args);
static void cmd_lora_preamble(char *args);
static void cmd_lora_syncword(char *args);
static void cmd_lora_iq(char *args);
static void cmd_lora_config(char *args);
static void cmd_lora_apply(char *args);
static void cmd_cc1352_fw_id(char *args);

// Command table
static const shell_cmd_t commands[] = {
	{ "help", cmd_help, "Show available commands", false },
	{ "boot", cmd_boot, "CC1352 bootloader mode", false },
	{ "exit", cmd_exit, "Return to passthrough", false },
	{ "band1", cmd_band1, "2.4GHz band", false },
	{ "band2", cmd_band2, "SUB-GHz band", false },
	{ "band3", cmd_band3, "LoRa band", false },
	{ "reboot", cmd_reboot, "RP2040 USB bootloader", false },
	{ "status", cmd_status, "Device status", false },
	{ "lora_freq", cmd_lora_freq, "Set frequency (Hz)", true },
	{ "lora_sf", cmd_lora_sf, "Set spreading factor", true },
	{ "lora_bw", cmd_lora_bw, "Set bandwidth (kHz)", true },
	{ "lora_cr", cmd_lora_cr, "Set coding rate", true },
	{ "lora_power", cmd_lora_power, "Set TX power (dBm)", true },
	{ "lora_mode", cmd_lora_mode, "stream|command mode", true },
	{ "lora_preamble", cmd_lora_preamble, "Set preamble length", true },
	{ "lora_syncword", cmd_lora_syncword, "private|public|<value>", true },
	{ "lora_iq", cmd_lora_iq, "normal|inverted IQ", true },
	{ "lora_config", cmd_lora_config, "Show LoRa config", false },
	{ "lora_apply", cmd_lora_apply, "Apply pending config", false },
	{ "cc1352_fw_id", cmd_cc1352_fw_id, "set|get|clear|list CC1352 FW ID",
	  true },
	{ NULL, NULL, NULL, false }
};

// Command implementations
static void cmd_help(char *args)
{
	shell_reply("Commands:\r\n");
	for (const shell_cmd_t *cmd = commands; cmd->name != NULL; cmd++) {
		char buf[64];
		snprintf(buf, sizeof(buf), "  %-8s - %s\r\n", cmd->name,
			 cmd->help);
		shell_reply(buf);
	}
}

static void cmd_boot(char *args)
{
	change_mode(BOOT);
	set_status_leds(0, 0, catsniffer.mode);
	shell_reply("BOOT\r\n");
}

static void cmd_exit(char *args)
{
	change_mode(PASSTHROUGH);
	set_status_leds(0, 0, 0);
	shell_reply("PASSTHROUGH\r\n");
}

static void cmd_band1(char *args)
{
	change_band(GIG);
	set_status_leds(0, 0, 0);
	shell_reply("2.4GHz Band\r\n");
}

static void cmd_band2(char *args)
{
	change_band(SUBGIG_1);
	set_status_leds(0, 0, 0);
	shell_reply("SUB-GHz Band\r\n");
}

static void cmd_band3(char *args)
{
	change_band(SUBGIG_2);
	set_status_leds(0, 0, 0);
	shell_reply("LoRa Band\r\n");
}

static void cmd_reboot(char *args)
{
	shell_reply("Entering USB bootloader...\r\n");
	k_msleep(100);
	reset_usb_boot(0, 0);
}

static void cmd_status(char *args)
{
	char buf[320];
	const char *mode_str = (catsniffer.lora_mode == LORA_MODE_STREAM) ?
				       "Stream" :
				       "Command";
	const char *lora_status =
		catsniffer.lora_initialized ? "initialized" : "not initialized";
	char fw_id[CC1352_FW_ID_MAX_LEN];
	const char *fw_id_str = "unset";
	const char *fw_type = "n/a";
	if (fw_metadata_get_cc1352_fw_id(fw_id, sizeof(fw_id)) == 0) {
		fw_id_str = fw_id;
		fw_type = fw_metadata_is_official_cc1352_fw_id(fw_id) ? "offici"
									"al" :
									"custo"
									"m";
	}
	snprintf(buf, sizeof(buf),
		 "Mode: %d, Band: %d, LoRa: %s, LoRa Mode: %s, CC1352 FW: %s "
		 "(%s)\r\n",
		 catsniffer.mode, catsniffer.band, lora_status, mode_str,
		 fw_id_str, fw_type);
	shell_reply(buf);
}

static void cmd_cc1352_fw_id(char *args)
{
	char *subcmd;
	char *value;

	while (*args && *args != ' ') {
		args++;
	}
	while (*args == ' ') {
		args++;
	}

	subcmd = args;
	while (*args && *args != ' ') {
		args++;
	}
	if (*args != '\0') {
		*args++ = '\0';
	}
	while (*args == ' ') {
		args++;
	}
	value = args;

	if (subcmd[0] == '\0') {
		shell_reply("Usage: cc1352_fw_id <set|get|clear|list> "
			    "[id]\r\n");
		return;
	}

	if (strcmp(subcmd, "set") == 0) {
		char msg[128];
		const char *type;
		int ret;

		if (value[0] == '\0') {
			shell_reply("Usage: cc1352_fw_id set <id>\r\n");
			return;
		}

		ret = fw_metadata_set_cc1352_fw_id(value);
		if (ret < 0) {
			if (ret == -EINVAL) {
				shell_reply("ERR invalid ID (allowed: a-z A-Z "
					    "0-9 _ - . , max 31)\r\n");
			} else {
				shell_reply("ERR storage unavailable\r\n");
			}
			return;
		}

		type = fw_metadata_is_official_cc1352_fw_id(value) ? "officia"
								     "l" :
								     "custom";
		snprintf(msg, sizeof(msg), "OK cc1352_fw_id=%s (%s)\r\n", value,
			 type);
		shell_reply(msg);
		return;
	}

	if (strcmp(subcmd, "get") == 0) {
		char fw_id[CC1352_FW_ID_MAX_LEN];
		char msg[128];
		int ret = fw_metadata_get_cc1352_fw_id(fw_id, sizeof(fw_id));
		if (ret == -ENOENT) {
			shell_reply("OK cc1352_fw_id=unset\r\n");
			return;
		}
		if (ret < 0) {
			shell_reply("ERR storage unavailable\r\n");
			return;
		}

		snprintf(msg, sizeof(msg), "OK cc1352_fw_id=%s type=%s\r\n",
			 fw_id,
			 fw_metadata_is_official_cc1352_fw_id(fw_id) ? "officia"
								       "l" :
								       "custo"
								       "m");
		shell_reply(msg);
		return;
	}

	if (strcmp(subcmd, "clear") == 0) {
		int ret = fw_metadata_clear_cc1352_fw_id();
		if (ret < 0) {
			shell_reply("ERR storage unavailable\r\n");
			return;
		}
		shell_reply("OK cc1352_fw_id cleared\r\n");
		return;
	}

	if (strcmp(subcmd, "list") == 0) {
		char msg[96];
		size_t count = fw_metadata_official_id_count();
		shell_reply("Official CC1352 FW IDs:\r\n");
		for (size_t i = 0; i < count; i++) {
			const char *id = fw_metadata_official_id_by_index(i);
			snprintf(msg, sizeof(msg), "  - %s\r\n", id);
			shell_reply(msg);
		}
		return;
	}

	shell_reply("Usage: cc1352_fw_id <set|get|clear|list> [id]\r\n");
}

static void cmd_lora_freq(char *args)
{
	// Skip command name to get argument
	while (*args && *args != ' ')
		args++;
	while (*args == ' ')
		args++;

	if (*args == '\0') {
		shell_reply("Usage: lora_freq <Hz>\r\n");
		return;
	}

	uint32_t freq = (uint32_t)atoi(args);
	if (freq < 137000000 || freq > 1020000000) {
		shell_reply("Error: Frequency must be 137-1020 MHz\r\n");
		return;
	}

	catsniffer.lora_config.frequency = freq;
	catsniffer.lora_config.config_pending = true;

	char buf[64];
	snprintf(buf, sizeof(buf), "Frequency set to %u Hz (pending)\r\n",
		 freq);
	shell_reply(buf);
}

static void cmd_lora_sf(char *args)
{
	// Skip command name to get argument
	while (*args && *args != ' ')
		args++;
	while (*args == ' ')
		args++;

	if (*args == '\0') {
		shell_reply("Usage: lora_sf <7-12>\r\n");
		return;
	}

	int sf = atoi(args);
	if (sf < 7 || sf > 12) {
		shell_reply("Error: Spreading factor must be 7-12\r\n");
		return;
	}

	// Map to Zephyr enum values (SF_7, SF_8, ..., SF_12)
	catsniffer.lora_config.spreading_factor = (uint8_t)sf;
	catsniffer.lora_config.config_pending = true;

	char buf[64];
	snprintf(buf, sizeof(buf), "Spreading Factor set to SF%d (pending)\r\n",
		 sf);
	shell_reply(buf);
}

static void cmd_lora_bw(char *args)
{
	// Skip command name to get argument
	while (*args && *args != ' ')
		args++;
	while (*args == ' ')
		args++;

	if (*args == '\0') {
		shell_reply("Usage: lora_bw <125|250|500>\r\n");
		return;
	}

	int bw = atoi(args);
	uint8_t bw_enum;

	switch (bw) {
	case 125:
		bw_enum = BW_125_KHZ;
		break;
	case 250:
		bw_enum = BW_250_KHZ;
		break;
	case 500:
		bw_enum = BW_500_KHZ;
		break;
	default:
		shell_reply("Error: Bandwidth must be 125, 250, or 500 "
			    "kHz\r\n");
		return;
	}

	catsniffer.lora_config.bandwidth = bw_enum;
	catsniffer.lora_config.config_pending = true;

	char buf[64];
	snprintf(buf, sizeof(buf), "Bandwidth set to %d kHz (pending)\r\n", bw);
	shell_reply(buf);
}

static void cmd_lora_cr(char *args)
{
	// Skip command name to get argument
	while (*args && *args != ' ')
		args++;
	while (*args == ' ')
		args++;

	if (*args == '\0') {
		shell_reply("Usage: lora_cr <5|6|7|8>\r\n");
		return;
	}

	int cr = atoi(args);
	uint8_t cr_enum;

	switch (cr) {
	case 5:
		cr_enum = CR_4_5;
		break;
	case 6:
		cr_enum = CR_4_6;
		break;
	case 7:
		cr_enum = CR_4_7;
		break;
	case 8:
		cr_enum = CR_4_8;
		break;
	default:
		shell_reply("Error: Coding rate must be 5, 6, 7, or 8 (for "
			    "4/5, 4/6, 4/7, 4/8)\r\n");
		return;
	}

	catsniffer.lora_config.coding_rate = cr_enum;
	catsniffer.lora_config.config_pending = true;

	char buf[64];
	snprintf(buf, sizeof(buf), "Coding Rate set to 4/%d (pending)\r\n", cr);
	shell_reply(buf);
}

static void cmd_lora_power(char *args)
{
	// Skip command name to get argument
	while (*args && *args != ' ')
		args++;
	while (*args == ' ')
		args++;

	if (*args == '\0') {
		shell_reply("Usage: lora_power <-9 to 22>\r\n");
		return;
	}

	int power = atoi(args);
	if (power < -9 || power > 22) {
		shell_reply("Error: TX power must be -9 to 22 dBm\r\n");
		return;
	}

	catsniffer.lora_config.tx_power = (int8_t)power;
	catsniffer.lora_config.config_pending = true;

	char buf[64];
	snprintf(buf, sizeof(buf), "TX Power set to %d dBm (pending)\r\n",
		 power);
	shell_reply(buf);
}

static void cmd_lora_mode(char *args)
{
	// Skip command name to get argument
	while (*args && *args != ' ')
		args++;
	while (*args == ' ')
		args++;

	if (*args == '\0') {
		shell_reply("Usage: lora_mode <stream|command>\r\n");
		return;
	}

	if (strncmp(args, "stream", 6) == 0) {
		catsniffer.lora_mode = LORA_MODE_STREAM;
		catsniffer.led_interval = 1000; // Slow blink for stream mode
		shell_reply("LoRa mode set to STREAM (slow blink)\r\n");
	} else if (strncmp(args, "command", 7) == 0) {
		catsniffer.lora_mode = LORA_MODE_COMMAND;
		catsniffer.led_interval = 200; // Fast blink for command mode
		shell_reply("LoRa mode set to COMMAND (fast blink)\r\n");
	} else {
		shell_reply("Error: Mode must be 'stream' or 'command'\r\n");
	}
}

static void cmd_lora_preamble(char *args)
{
	// Skip command name to get argument
	while (*args && *args != ' ')
		args++;
	while (*args == ' ')
		args++;

	if (*args == '\0') {
		shell_reply("Usage: lora_preamble <6-65535>\r\n");
		return;
	}

	int preamble = atoi(args);
	if (preamble < 6 || preamble > 65535) {
		shell_reply("Error: Preamble length must be 6-65535\r\n");
		return;
	}

	catsniffer.lora_config.preamble_len = (uint16_t)preamble;
	catsniffer.lora_config.config_pending = true;

	char buf[64];
	snprintf(buf, sizeof(buf), "Preamble length set to %d (pending)\r\n",
		 preamble);
	shell_reply(buf);
}

static void cmd_lora_syncword(char *args)
{
	// Skip command name to get argument
	while (*args && *args != ' ')
		args++;
	while (*args == ' ')
		args++;

	if (*args == '\0') {
		shell_reply("Usage: lora_syncword <private|public|value>\r\n");
		return;
	}

	if (strncmp(args, "private", 7) == 0) {
		catsniffer.lora_config.syncword = 0x1424;
		catsniffer.lora_config.config_pending = true;
		shell_reply("Sync word set to PRIVATE (0x1424) (pending)\r\n");
	} else if (strncmp(args, "public", 6) == 0) {
		catsniffer.lora_config.syncword = 0x3444;
		catsniffer.lora_config.config_pending = true;
		shell_reply("Sync word set to PUBLIC (0x3444) (pending)\r\n");
	} else {
		uint16_t sw_val = (uint16_t)strtol(args, NULL, 0);
		if (sw_val > 0) {
			if (sw_val <= 0xFF) {
				sw_val = (sw_val << 8) | 0x44;
			}
			catsniffer.lora_config.syncword = sw_val;
			catsniffer.lora_config.config_pending = true;
			char buf[64];
			snprintf(buf, sizeof(buf),
				 "Sync word set to 0x%04X (pending)\r\n",
				 sw_val);
			shell_reply(buf);
		} else {
			shell_reply("Error: Must be 'private', 'public' or a "
				    "value\r\n");
		}
	}
}

static void cmd_lora_iq(char *args)
{
	// Skip command name to get argument
	while (*args && *args != ' ')
		args++;
	while (*args == ' ')
		args++;

	if (*args == '\0') {
		shell_reply("Usage: lora_iq <normal|inverted>\r\n");
		return;
	}

	if (strncmp(args, "normal", 6) == 0) {
		catsniffer.lora_config.iq_inverted = false;
		catsniffer.lora_config.config_pending = true;
		shell_reply("IQ set to NORMAL (pending)\r\n");
	} else if (strncmp(args, "inverted", 8) == 0) {
		catsniffer.lora_config.iq_inverted = true;
		catsniffer.lora_config.config_pending = true;
		shell_reply("IQ set to INVERTED (pending)\r\n");
	} else {
		shell_reply("Error: Must be 'normal' or 'inverted'\r\n");
	}
}

static void cmd_lora_config(char *args)
{
	char buf[512];
	const char *mode_str = (catsniffer.lora_mode == LORA_MODE_STREAM) ?
				       "Stream" :
				       "Command";
	const char *pending_str =
		catsniffer.lora_config.config_pending ? " (pending apply)" : "";
	const char *iq_str = catsniffer.lora_config.iq_inverted ? "Inverted" :
								  "Normal";
	char syncword_str[32];
	snprintf(syncword_str, sizeof(syncword_str), "0x%04X",
		 catsniffer.lora_config.syncword);

	snprintf(buf, sizeof(buf),
		 "LoRa Configuration:%s\r\n"
		 "  Frequency: %u Hz\r\n"
		 "  Spreading Factor: SF%d\r\n"
		 "  Bandwidth: %s kHz\r\n"
		 "  Coding Rate: 4/%d\r\n"
		 "  TX Power: %d dBm\r\n"
		 "  Preamble Length: %d\r\n"
		 "  IQ: %s\r\n"
		 "  Sync Word: %s\r\n"
		 "  Mode: %s\r\n",
		 pending_str, catsniffer.lora_config.frequency,
		 catsniffer.lora_config.spreading_factor,
		 (catsniffer.lora_config.bandwidth == BW_125_KHZ) ? "125" :
		 (catsniffer.lora_config.bandwidth == BW_250_KHZ) ? "250" :
								    "500",
		 (catsniffer.lora_config.coding_rate == CR_4_5) ? 5 :
		 (catsniffer.lora_config.coding_rate == CR_4_6) ? 6 :
		 (catsniffer.lora_config.coding_rate == CR_4_7) ? 7 :
								  8,
		 catsniffer.lora_config.tx_power,
		 catsniffer.lora_config.preamble_len, iq_str, syncword_str,
		 mode_str);
	shell_reply(buf);
}

static void cmd_lora_apply(char *args)
{
	if (!catsniffer.lora_config.config_pending) {
		shell_reply("No pending configuration changes\r\n");
		return;
	}

	int ret = apply_lora_config();
	if (ret < 0) {
		char buf[64];
		snprintf(buf, sizeof(buf),
			 "Error applying configuration: %d\r\n", ret);
		shell_reply(buf);
	} else {
		catsniffer.lora_config.config_pending = false;
		shell_reply("LoRa configuration applied successfully\r\n");
	}
}

// Main command processor
void process_command(char *cmd, size_t len)
{
	if (len == 0)
		return;

	for (const shell_cmd_t *entry = commands; entry->name != NULL;
	     entry++) {
		if (entry->prefix_match) {
			size_t name_len = strlen(entry->name);
			if (strncmp(cmd, entry->name, name_len) == 0) {
				entry->handler(cmd);
				return;
			}
		} else {
			if (strcmp(cmd, entry->name) == 0) {
				entry->handler(cmd);
				return;
			}
		}
	}

	shell_reply("Unknown command. Type 'help'\r\n");
}
