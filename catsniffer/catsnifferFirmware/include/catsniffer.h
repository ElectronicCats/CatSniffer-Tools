/*
 * Catsniffer Dual USB CDC-ACM Header
 * Eduardo Contreras @ Electronic Cats 2026
 */

#ifndef CATSNIFFER_H
#define CATSNIFFER_H

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/gpio.h>
#include <catsniffer_usbd.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/sys/ring_buffer.h>
#include <zephyr/usb/usbd.h>
#include <zephyr/drivers/spi.h>
#include <zephyr/drivers/lora.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/util.h>
#include <string.h>
#include <stdlib.h>

// Ring buffer and command buffer sizes
#define RING_BUF_SIZE 1024
#define COMMAND_BUF_SIZE 256

// Define Thead priorities
#define LORA_THREAD_PRIORITY K_PRIO_COOP(5)
#define MAIN_THREAD_PRIORITY K_PRIO_COOP(7)

// Helper macro to simplify GPIO setup
#define INIT_GPIO(name, flags)                                         \
	const struct gpio_dt_spec name =                               \
		GPIO_DT_SPEC_GET_OR(DT_ALIAS(name), gpios, { 0 });     \
	do {                                                           \
		if (!device_is_ready(name.port)) {                     \
			printk("Error: " #name " device not ready\n"); \
			return 1;                                      \
		}                                                      \
		gpio_pin_configure_dt(&name, flags);                   \
	} while (0)

// Mode definitions
enum MODE {
	PASSTHROUGH = 0, // CC1352 passthrough @ 921600 baud
	BOOT = 1,	 // CC1352 bootloader @ 500000 baud
};

// Band definitions
enum BAND {
	GIG = 0,      // 2.4GHz CC1352
	SUBGIG_1 = 1, // Sub-GHz CC1352
	SUBGIG_2 = 2  // LoRa SX1262
};

// LoRa mode definitions
enum LORA_MODE {
	LORA_MODE_STREAM = 0,  // Default: raw binary
	LORA_MODE_COMMAND = 1, // Text commands
};

// LoRa configuration structure
typedef struct {
	uint32_t frequency;	  // Hz (default: 915000000)
	uint8_t spreading_factor; // SF_7 to SF_12 (default: SF_7)
	uint8_t bandwidth;   // BW_125_KHZ, BW_250_KHZ, BW_500_KHZ (default:
			     // BW_125_KHZ)
	uint8_t coding_rate; // CR_4_5, CR_4_6, CR_4_7, CR_4_8 (default: CR_4_5)
	int8_t tx_power;     // -9 to 22 dBm (default: 20)
	uint16_t preamble_len; // Default: 12
	bool iq_inverted;      // IQ inversion (default: false/normal)
	bool public_network;   // Public network sync word (default: false/private)
	uint16_t syncword; // Sync word: e.g. 0x1424 (Private), 0x3444 (Public),
			   // 0x2B44 (Meshtastic)
	bool config_pending; // true if changes not yet applied
} lora_config_t;

// Catsniffer state structure
typedef struct {
	uint8_t mode;
	uint8_t band;
	unsigned long led_interval;
	int64_t previous_millis;
	unsigned long baud;
	bool command_recognized;
	uint8_t command_counter;
	char command_data[COMMAND_BUF_SIZE];
	size_t command_data_len;
	// LoRa state
	uint8_t lora_mode;	   // LORA_MODE_STREAM or LORA_MODE_COMMAND
	lora_config_t lora_config; // Current LoRa configuration
	bool lora_initialized;	   // Track initialization state
	bool lora_config_lock;	   // Lock flag to pause LoRa operations during
				   // reconfiguration
} catsniffer_t;

// Global catsniffer instance
extern catsniffer_t catsniffer;

// LoRa command format (CDC1):
// TX <hex_data>     - Send LoRa packet (e.g., "TX 48656C6C6F")
// RX [timeout_ms]   - Enter receive mode (e.g., "RX 5000" or "RX" for
// continuous) FREQ <frequency>  - Set frequency in Hz (e.g., "FREQ 868000000")
// SF <7-12>         - Set spreading factor (e.g., "SF 7")
// PWR <-9 to 22>    - Set TX power in dBm (e.g., "PWR 14")
// STATUS            - Get device status

// Function prototypes
void reset_cc1352(void);
void boot_mode_cc1352(void);
void change_baud(unsigned long new_baud);
void change_band(unsigned long new_band);
void change_mode(unsigned long new_mode);
void process_lora_command(char *cmd_line);
int apply_lora_config(void);

#endif /* CATSNIFFER_H */
