/*
 * Complete Dual USB CDC-ACM Catsniffer Firmware
 * Eduardo Contreras @ Electronic Cats 2026
 *
 */
#include "catsniffer.h"
#include "fw_metadata.h"
#include "shell_commands.h"

LOG_MODULE_REGISTER(catsniffer_main, LOG_LEVEL_INF);

#define CDC0_NODE DT_NODELABEL(cdc_acm_uart0)
#define CDC1_NODE DT_NODELABEL(cdc_acm_uart1)
#define CDC2_NODE DT_NODELABEL(cdc_acm_uart2)

// Device definitions
#define CC1352_UART DEVICE_DT_GET(DT_CHOSEN(uart_cc1352))
#define CDC0_DEV DEVICE_DT_GET(CDC0_NODE)
#define CDC1_DEV DEVICE_DT_GET(CDC1_NODE)
#define CDC2_DEV DEVICE_DT_GET(CDC2_NODE)

// Communication buffers
uint8_t ring_cc1352_to_usb[RING_BUF_SIZE];
uint8_t ring_usb_to_cc1352[RING_BUF_SIZE];
uint8_t ring_sx1262_to_usb[RING_BUF_SIZE];
uint8_t ring_usb_to_sx1262[RING_BUF_SIZE];
uint8_t ring_config_to_usb[RING_BUF_SIZE];
uint8_t ring_usb_to_config[RING_BUF_SIZE];

struct ring_buf rb_cc1352_to_usb;
struct ring_buf rb_usb_to_cc1352;
struct ring_buf rb_sx1262_to_usb;
struct ring_buf rb_usb_to_sx1262;
struct ring_buf rb_config_to_usb;
struct ring_buf rb_usb_to_config;

// Device references
const struct device *uart_cc1352;
const struct device *cdc0_dev;
const struct device *cdc1_dev;
const struct device *cdc2_dev;

// Export LoRaMac-node SPI function
extern void SX126xWriteRegister(uint16_t address, uint8_t value);

// Global catsniffer instance
catsniffer_t catsniffer = {0};

// GPIO for CC1352 control
static const struct gpio_dt_spec pin_reset =
    GPIO_DT_SPEC_GET(DT_ALIAS(pin_reset), gpios);
static const struct gpio_dt_spec pin_boot =
    GPIO_DT_SPEC_GET(DT_ALIAS(pin_boot), gpios);
// GPIO for LED control
static const struct gpio_dt_spec led0 = GPIO_DT_SPEC_GET(DT_ALIAS(led0), gpios);
static const struct gpio_dt_spec led1 = GPIO_DT_SPEC_GET(DT_ALIAS(led1), gpios);
static const struct gpio_dt_spec led2 = GPIO_DT_SPEC_GET(DT_ALIAS(led2), gpios);

// GPIO for cJTAG RFU
static const struct gpio_dt_spec cjtag0 =
    GPIO_DT_SPEC_GET(DT_ALIAS(cjtag0), gpios);
static const struct gpio_dt_spec cjtag1 =
    GPIO_DT_SPEC_GET(DT_ALIAS(cjtag1), gpios);
static const struct gpio_dt_spec cjtag2 =
    GPIO_DT_SPEC_GET(DT_ALIAS(cjtag2), gpios);
static const struct gpio_dt_spec cjtag3 =
    GPIO_DT_SPEC_GET(DT_ALIAS(cjtag3), gpios);

// GPIO for RF switch
static const struct gpio_dt_spec ctf1 = GPIO_DT_SPEC_GET(DT_ALIAS(ctf1), gpios);
static const struct gpio_dt_spec ctf2 = GPIO_DT_SPEC_GET(DT_ALIAS(ctf2), gpios);
static const struct gpio_dt_spec ctf3 = GPIO_DT_SPEC_GET(DT_ALIAS(ctf3), gpios);

// LED array for cycling animation
const struct gpio_dt_spec *LEDs[3] = {&led2, &led0, &led1};

// USB context
static struct usbd_context *catsniffer_usbd;

static const struct device *lora_dev;

// Thread definitions
#define LORA_THREAD_STACK_SIZE 2048
K_THREAD_STACK_DEFINE(lora_thread_stack, LORA_THREAD_STACK_SIZE);
static struct k_thread lora_thread;
K_SEM_DEFINE(lora_data_sem, 0, 1);

// Helpers for ring buffers
static inline uint32_t safe_ring_buf_put(struct ring_buf *rb,
                                         const uint8_t *data, uint32_t size) {
  unsigned int key = irq_lock();
  uint32_t result = ring_buf_put(rb, data, size);
  irq_unlock(key);
  return result;
}

static inline uint32_t safe_ring_buf_get(struct ring_buf *rb, uint8_t *data,
                                         uint32_t size) {
  unsigned int key = irq_lock();
  uint32_t result = ring_buf_get(rb, data, size);
  irq_unlock(key);
  return result;
}

void lora_rx_cb(const struct device *dev, uint8_t *data, uint16_t size,
                int16_t rssi, int8_t snr, void *user_data) {
  ARG_UNUSED(dev);
  ARG_UNUSED(user_data);

  char rx_msg[384];

  // Create hex string of the data
  char data_str[128] = {0};
  int display_len = (size > 40) ? 40 : size;

  for (int i = 0; i < display_len; i++) {
    char byte_str[4];
    snprintf(byte_str, sizeof(byte_str), "%02X", data[i]);
    strcat(data_str, byte_str);
  }
  if (size > 40)
    strcat(data_str, "...");

  snprintf(rx_msg, sizeof(rx_msg), "RX: %s | RSSI: %d | SNR: %d\r\n", data_str,
           rssi, snr);
  safe_ring_buf_put(&rb_sx1262_to_usb, (uint8_t *)rx_msg, strlen(rx_msg));
  if (cdc1_dev)
    uart_irq_tx_enable(cdc1_dev);

  // En Zephyr, después de invocar lora_recv_async y recibir 1 mensaje, la radio
  // sale del modo de escucha contínua automáticamente. Al disparar el semáforo
  // aquí, el hilo principal de LoRa es despertado y llama auto-mágicamente a
  // lora_start_rx_async() para reiniciar la escucha inmediatamente.
  k_sem_give(&lora_data_sem);
}

// USB message callback
static void catsniffer_usb_msg_cb(struct usbd_context *const ctx,
                                  const struct usbd_msg *msg) {
  if (usbd_can_detect_vbus(ctx)) {
    if (msg->type == USBD_MSG_VBUS_READY) {
      usbd_enable(ctx);
    } else if (msg->type == USBD_MSG_VBUS_REMOVED) {
      usbd_disable(ctx);
    }
  }
}

// Enable USB device
static int enable_usb_device_next(void) {
  catsniffer_usbd = usbd_init_device(catsniffer_usb_msg_cb);
  if (catsniffer_usbd == NULL) {
    return -ENODEV;
  }
  if (!usbd_can_detect_vbus(catsniffer_usbd)) {
    return usbd_enable(catsniffer_usbd);
  }
  return 0;
}

// CC1352 UART interrupt handler
static void cc1352_uart_interrupt_handler(const struct device *dev,
                                          void *user_data) {
  while (uart_irq_update(dev) && uart_irq_is_pending(dev)) {
    if (uart_irq_rx_ready(dev)) {
      uint8_t buf[64];
      int len = uart_fifo_read(dev, buf, sizeof(buf));
      if (len > 0) {
        safe_ring_buf_put(&rb_cc1352_to_usb, buf, len);
        uart_irq_tx_enable(cdc0_dev);
      }
    }

    if (uart_irq_tx_ready(dev)) {
      uint8_t buf[64];
      int len = safe_ring_buf_get(&rb_usb_to_cc1352, buf, sizeof(buf));
      if (len > 0) {
        uart_fifo_fill(dev, buf, len);
      } else {
        uart_irq_tx_disable(dev);
      }
    }
  }
}

// CDC0 (CC1352) interrupt handler - PURE BRIDGE
static void cdc0_interrupt_handler(const struct device *dev, void *user_data) {
  while (uart_irq_update(dev) && uart_irq_is_pending(dev)) {
    if (uart_irq_rx_ready(dev)) {
      uint8_t buf[64];
      int len = uart_fifo_read(dev, buf, sizeof(buf));
      for (int i = 0; i < len; i++) {
        uint8_t data = buf[i];
        safe_ring_buf_put(&rb_usb_to_cc1352, &data, 1);
        uart_irq_tx_enable(uart_cc1352);
      }
    }

    if (uart_irq_tx_ready(dev)) {
      uint8_t buf[64];
      int len = safe_ring_buf_get(&rb_cc1352_to_usb, buf, sizeof(buf));
      if (len > 0) {
        uart_fifo_fill(dev, buf, len);
      } else {
        uart_irq_tx_disable(dev);
      }
    }
  }
}

// CDC2 (Config/Debug) interrupt handler - TEXT SHELL
static void cdc2_interrupt_handler(const struct device *dev, void *user_data) {
  while (uart_irq_update(dev) && uart_irq_is_pending(dev)) {
    if (uart_irq_rx_ready(dev)) {
      uint8_t buf[64];
      int len = uart_fifo_read(dev, buf, sizeof(buf));

      for (int i = 0; i < len; i++) {
        uint8_t data = buf[i];

        // Echo back for terminal feeling?
        safe_ring_buf_put(&rb_config_to_usb, &data, 1);
        uart_irq_tx_enable(dev);

        // Simple line buffering
        if (data == '\n' || data == '\r') {
          if (catsniffer.command_data_len > 0) {
            catsniffer.command_data[catsniffer.command_data_len] = '\0';
            process_command(catsniffer.command_data,
                            catsniffer.command_data_len);
            catsniffer.command_data_len = 0;
          }
        } else if (catsniffer.command_data_len < COMMAND_BUF_SIZE - 1) {
          catsniffer.command_data[catsniffer.command_data_len++] = data;
        }
      }
    }

    if (uart_irq_tx_ready(dev)) {
      uint8_t buf[64];
      int len = safe_ring_buf_get(&rb_config_to_usb, buf, sizeof(buf));
      if (len > 0) {
        uart_fifo_fill(dev, buf, len);
      } else {
        uart_irq_tx_disable(dev);
      }
    }
  }
}

// CDC1 (SX1262) interrupt handler
static void cdc1_interrupt_handler(const struct device *dev, void *user_data) {
  while (uart_irq_update(dev) && uart_irq_is_pending(dev)) {
    if (uart_irq_rx_ready(dev)) {
      uint8_t buf[64];
      int len = uart_fifo_read(dev, buf, sizeof(buf));
      if (len > 0) {
        safe_ring_buf_put(&rb_usb_to_sx1262, buf, len);
        k_sem_give(&lora_data_sem); // Wake up LoRa
                                    // thread
      }
    }

    if (uart_irq_tx_ready(dev)) {
      uint8_t buf[64];

      int len = safe_ring_buf_get(&rb_sx1262_to_usb, buf, sizeof(buf));
      if (len > 0) {
        uart_fifo_fill(dev, buf, len);
      } else {
        uart_irq_tx_disable(dev);
      }
    }
  }
}

void reset_cc1352(void) {
  gpio_pin_set_dt(&pin_reset, 0);
  k_msleep(100);
  gpio_pin_set_dt(&pin_reset, 1);
  k_msleep(100);
}

void boot_mode_cc1352(void) {
  gpio_pin_configure_dt(&pin_boot, GPIO_OUTPUT);
  gpio_pin_set_dt(&pin_boot, 0);
  k_msleep(100);
  reset_cc1352();
}

void change_baud(unsigned long new_baud) {
  if (new_baud == catsniffer.baud)
    return;

  uart_irq_tx_disable(uart_cc1352);
  uart_irq_rx_disable(uart_cc1352);

  struct uart_config cfg;
  uart_config_get(uart_cc1352, &cfg);
  cfg.baudrate = new_baud;
  uart_configure(uart_cc1352, &cfg);
  catsniffer.baud = new_baud;

  // Re-enable interrupts
  uart_irq_rx_enable(uart_cc1352);
}

void change_band(unsigned long new_band) {
  if (new_band == catsniffer.band)
    return;

  switch (new_band) {
  case GIG:
    gpio_pin_set_dt(&ctf1, 0);
    gpio_pin_set_dt(&ctf2, 1);
    gpio_pin_set_dt(&ctf3, 0);
    break;
  case SUBGIG_1:
    gpio_pin_set_dt(&ctf1, 0);
    gpio_pin_set_dt(&ctf2, 0);
    gpio_pin_set_dt(&ctf3, 1);
    break;
  case SUBGIG_2:
    gpio_pin_set_dt(&ctf1, 1);
    gpio_pin_set_dt(&ctf2, 0);
    gpio_pin_set_dt(&ctf3, 0);
    break;
  }
  catsniffer.band = new_band;
}

void change_mode(unsigned long new_mode) {
  if (new_mode == catsniffer.mode)
    return;

  catsniffer.mode = new_mode;

  switch (new_mode) {
  case BOOT:
    catsniffer.led_interval = 200;
    boot_mode_cc1352();
    reset_cc1352();
    k_msleep(200);
    change_baud(500000);
    break;
  case PASSTHROUGH:
    gpio_pin_configure_dt(&pin_boot, GPIO_INPUT | GPIO_PULL_UP);
    reset_cc1352();
    catsniffer.led_interval = 1000;
    change_baud(921600);
    break;
  }
}

// Shell Helpers (Exposed to shell_commands.c) ---

void shell_reply(const char *msg) {
  if (!msg)
    return;
  safe_ring_buf_put(&rb_config_to_usb, (uint8_t *)msg, strlen(msg));
  if (cdc2_dev)
    uart_irq_tx_enable(cdc2_dev);
}

void set_status_leds(int l0, int l1, int l2) {
  gpio_pin_set_dt(&led0, l0);
  gpio_pin_set_dt(&led1, l1);
  gpio_pin_set_dt(&led2, l2);
}

// Forward declarations
static const char *get_error_string(int error);
static int lora_set_tx_mode(void);
static void lora_stop_rx(void);
static int lora_start_rx_async(void);

int initialize_lora(void) {
  const char *status_msg;

  if (catsniffer.lora_initialized) {
    status_msg = "LoRa: Already initialized\r\n";
    safe_ring_buf_put(&rb_config_to_usb, (uint8_t *)status_msg,
                      strlen(status_msg));
    if (cdc2_dev)
      uart_irq_tx_enable(cdc2_dev);
    return 0;
  }

  status_msg = "LoRa: Starting initialization...\r\n";
  safe_ring_buf_put(&rb_config_to_usb, (uint8_t *)status_msg,
                    strlen(status_msg));
  if (cdc2_dev)
    uart_irq_tx_enable(cdc2_dev);

  lora_dev = DEVICE_DT_GET(DT_ALIAS(lora0));
  if (!device_is_ready(lora_dev)) {
    status_msg = "ERROR: LoRa device not ready\r\n";
    safe_ring_buf_put(&rb_config_to_usb, (uint8_t *)status_msg,
                      strlen(status_msg));
    if (cdc2_dev)
      uart_irq_tx_enable(cdc2_dev);
    return -ENODEV;
  }

  status_msg = "LoRa: Device ready\r\n";
  safe_ring_buf_put(&rb_config_to_usb, (uint8_t *)status_msg,
                    strlen(status_msg));
  if (cdc2_dev)
    uart_irq_tx_enable(cdc2_dev);

  struct lora_modem_config config;
  config.frequency = catsniffer.lora_config.frequency;
  config.bandwidth = catsniffer.lora_config.bandwidth;
  config.datarate = catsniffer.lora_config.spreading_factor;
  config.preamble_len = catsniffer.lora_config.preamble_len;
  config.coding_rate = catsniffer.lora_config.coding_rate;
  config.tx_power = catsniffer.lora_config.tx_power;
  config.tx = false; // Start in RX mode to enable receiving
  config.iq_inverted = catsniffer.lora_config.iq_inverted;
  config.public_network = false;

  int ret = lora_config(lora_dev, &config);
  if (ret < 0) {
    status_msg = "ERROR: LoRa configuration failed\r\n";
    safe_ring_buf_put(&rb_config_to_usb, (uint8_t *)status_msg,
                      strlen(status_msg));
    if (cdc2_dev)
      uart_irq_tx_enable(cdc2_dev);
    return ret;
  }

  // Inject custom Sync Word directly
  SX126xWriteRegister(0x0740, (catsniffer.lora_config.syncword >> 8) & 0xFF);
  SX126xWriteRegister(0x0741, catsniffer.lora_config.syncword & 0xFF);

  catsniffer.lora_initialized = true;
  catsniffer.lora_config_lock = false;
  status_msg = "LoRa: Initialization completed (RX mode)!\r\n";
  safe_ring_buf_put(&rb_config_to_usb, (uint8_t *)status_msg,
                    strlen(status_msg));
  if (cdc2_dev)
    uart_irq_tx_enable(cdc2_dev);

  return 0;
}

int apply_lora_config(void) {
  const char *status_msg;

  if (!catsniffer.lora_initialized) {
    status_msg = "Error: LoRa not initialized. Use TEST command "
                 "first.\r\n";
    safe_ring_buf_put(&rb_config_to_usb, (uint8_t *)status_msg,
                      strlen(status_msg));
    if (cdc2_dev)
      uart_irq_tx_enable(cdc2_dev);
    return -ENODEV;
  }

  // Lock to prevent LoRa thread from interfering
  catsniffer.lora_config_lock = true;
  k_msleep(50); // Wait for any ongoing operation to complete

  // Free radio from Rx
  lora_recv_async(lora_dev, NULL, NULL);

  status_msg = "Applying LoRa configuration...\r\n";
  safe_ring_buf_put(&rb_config_to_usb, (uint8_t *)status_msg,
                    strlen(status_msg));
  if (cdc2_dev)
    uart_irq_tx_enable(cdc2_dev);

  struct lora_modem_config config;
  config.frequency = catsniffer.lora_config.frequency;
  config.bandwidth = catsniffer.lora_config.bandwidth;
  config.datarate = catsniffer.lora_config.spreading_factor;
  config.preamble_len = catsniffer.lora_config.preamble_len;
  config.coding_rate = catsniffer.lora_config.coding_rate;
  config.tx_power = catsniffer.lora_config.tx_power;
  config.tx = false; // Configure for RX mode
  config.iq_inverted = catsniffer.lora_config.iq_inverted;
  config.public_network = false;

  int ret = lora_config(lora_dev, &config);
  if (ret == 0) {
    SX126xWriteRegister(0x0740, (catsniffer.lora_config.syncword >> 8) & 0xFF);
    SX126xWriteRegister(0x0741, catsniffer.lora_config.syncword & 0xFF);
  }

  // Unlock regardless of result
  catsniffer.lora_config_lock = false;

  if (ret < 0) {
    char err_buf[96];
    snprintf(err_buf, sizeof(err_buf),
             "ERROR: LoRa configuration failed (%d: %s)\r\n", ret,
             get_error_string(ret));
    safe_ring_buf_put(&rb_config_to_usb, (uint8_t *)err_buf, strlen(err_buf));
    if (cdc2_dev)
      uart_irq_tx_enable(cdc2_dev);
    return ret;
  }

  // Forzamos al hilo a despertar para invocar lora_start_rx_async() e iniciar
  // en RX mode.
  k_sem_give(&lora_data_sem);

  status_msg = "LoRa configuration applied successfully (RX mode)\r\n";
  safe_ring_buf_put(&rb_config_to_usb, (uint8_t *)status_msg,
                    strlen(status_msg));
  if (cdc2_dev)
    uart_irq_tx_enable(cdc2_dev);

  return 0;
}

static const char *get_error_string(int error) {
  switch (error) {
  case 0:
    return "Success";
  case -EAGAIN:
    return "EAGAIN - Resource temporarily unavailable";
  case -EBUSY:
    return "EBUSY - Device busy";
  case -EIO:
    return "EIO - I/O error";
  case -EINVAL:
    return "EINVAL - Invalid argument";
  case -ENODEV:
    return "ENODEV - Device not ready";
  case -ENOTSUP:
    return "ENOTSUP - Operation not supported";
  case -ETIMEDOUT:
    return "ETIMEDOUT - Timeout";
  default:
    return "Unknown error";
  }
}

// Exposed for shell_commands.c
void process_lora_command(char *cmd_line) {
  char response[384]; // Increased size to prevent warning
  const char *status_msg;

  if (!catsniffer.lora_initialized) {
    int ret = initialize_lora();
    if (ret < 0)
      return;
  }

  if (strncmp(cmd_line, "TEST", 4) == 0) {
    status_msg = "TEST: LoRa ready!\r\n";
    safe_ring_buf_put(&rb_config_to_usb, (uint8_t *)status_msg,
                      strlen(status_msg));
    if (cdc2_dev)
      uart_irq_tx_enable(cdc2_dev);
    return;
  }

  if (strncmp(cmd_line, "TXTEST", 6) == 0) {
    if (!catsniffer.lora_initialized) {
      status_msg = "ERROR: LoRa not initialized\r\n";
      safe_ring_buf_put(&rb_config_to_usb, (uint8_t *)status_msg,
                        strlen(status_msg));
      if (cdc2_dev)
        uart_irq_tx_enable(cdc2_dev);
      return;
    }

    uint8_t tx_data[] = "PING"; // Simple payload
    status_msg = "DEBUG: Sending PING packet\r\n";
    safe_ring_buf_put(&rb_config_to_usb, (uint8_t *)status_msg,
                      strlen(status_msg));
    if (cdc2_dev)
      uart_irq_tx_enable(cdc2_dev);

    // Switch to TX mode, send, then back to RX mode
    lora_stop_rx();
    lora_set_tx_mode();
    int ret = lora_send(lora_dev, tx_data, sizeof(tx_data));
    lora_start_rx_async();

    snprintf(response, sizeof(response), "TX Result: %d (%s)\r\n", ret,
             get_error_string(ret));
    safe_ring_buf_put(&rb_config_to_usb, (uint8_t *)response, strlen(response));
    if (cdc2_dev)
      uart_irq_tx_enable(cdc2_dev);
    return;
  }

  if (strncmp(cmd_line, "TX ", 3) == 0) {
    if (!catsniffer.lora_initialized) {
      status_msg = "ERROR: LoRa not initialized\r\n";
      safe_ring_buf_put(&rb_config_to_usb, (uint8_t *)status_msg,
                        strlen(status_msg));
      if (cdc2_dev)
        uart_irq_tx_enable(cdc2_dev);
      return;
    }

    char *hex_data = &cmd_line[3];
    uint8_t tx_data[128];
    size_t hex_len = strlen(hex_data);

    // Debug: Show what we're trying to send
    snprintf(response, sizeof(response),
             "DEBUG: Hex input '%s', length %zu\r\n", hex_data, hex_len);
    safe_ring_buf_put(&rb_config_to_usb, (uint8_t *)response, strlen(response));
    if (cdc2_dev)
      uart_irq_tx_enable(cdc2_dev);

    if (hex_len % 2 == 0 && hex_len > 0) {
      size_t data_len = hex_len / 2;

      // Debug: Check data length
      snprintf(response, sizeof(response), "DEBUG: Converting to %zu bytes\r\n",
               data_len);
      safe_ring_buf_put(&rb_config_to_usb, (uint8_t *)response,
                        strlen(response));
      if (cdc2_dev)
        uart_irq_tx_enable(cdc2_dev);

      for (size_t i = 0; i < data_len; i++) {
        char hex_byte[3] = {hex_data[i * 2], hex_data[i * 2 + 1], '\0'};
        tx_data[i] = (uint8_t)strtoul(hex_byte, NULL, 16);
      }

      // Debug: Show converted data
      char debug_hex[256] = {0};
      for (size_t i = 0; i < data_len; i++) {
        snprintf(&debug_hex[i * 3], 4, "%02X ", tx_data[i]);
      }
      snprintf(response, sizeof(response), "DEBUG: Sending bytes %s\r\n",
               debug_hex);
      safe_ring_buf_put(&rb_config_to_usb, (uint8_t *)response,
                        strlen(response));
      if (cdc2_dev)
        uart_irq_tx_enable(cdc2_dev);

      lora_stop_rx();
      // Switch to TX mode, send, then back to RX mode
      lora_set_tx_mode();
      int ret = lora_send(lora_dev, tx_data, data_len);
      lora_start_rx_async();

      snprintf(response, sizeof(response), "TX Result: %d (%s)\r\n", ret,
               get_error_string(ret));

    } else {
      status_msg = "ERROR: Invalid hex data length\r\n";
      snprintf(response, sizeof(response), "%s", status_msg);
    }

    safe_ring_buf_put(&rb_config_to_usb, (uint8_t *)response, strlen(response));
    if (cdc2_dev)
      uart_irq_tx_enable(cdc2_dev);
    return;
  }

  status_msg = "Available: TEST, TX <hex>\r\n";
  safe_ring_buf_put(&rb_config_to_usb, (uint8_t *)status_msg,
                    strlen(status_msg));
  if (cdc2_dev)
    uart_irq_tx_enable(cdc2_dev);
}

// Detiene explícitamente la recepción asíncrona
static void lora_stop_rx(void) {
  // Pasar NULL y NULL cancela la recepción asíncrona en Zephyr
  lora_recv_async(lora_dev, NULL, NULL);

  // IMPORTANTE: Dar un pequeño respiro al bus SPI/Driver para cambiar de
  // estado
  k_sleep(K_MSEC(5));
}

// Helper function to configure LoRa for TX
static int lora_set_tx_mode(void) {
  struct lora_modem_config config;
  config.frequency = catsniffer.lora_config.frequency;
  config.bandwidth = catsniffer.lora_config.bandwidth;
  config.datarate = catsniffer.lora_config.spreading_factor;
  config.preamble_len = catsniffer.lora_config.preamble_len;
  config.coding_rate = catsniffer.lora_config.coding_rate;
  config.tx_power = catsniffer.lora_config.tx_power;
  config.tx = true;
  config.iq_inverted = catsniffer.lora_config.iq_inverted;
  config.public_network = false;

  int ret = lora_config(lora_dev, &config);
  if (ret == 0) {
    SX126xWriteRegister(0x0740, (catsniffer.lora_config.syncword >> 8) & 0xFF);
    SX126xWriteRegister(0x0741, catsniffer.lora_config.syncword & 0xFF);
  }
  return ret;
}

// Helper function to configure LoRa for RX
static int lora_start_rx_async(void) {
  struct lora_modem_config config;
  config.frequency = catsniffer.lora_config.frequency;
  config.bandwidth = catsniffer.lora_config.bandwidth;
  config.datarate = catsniffer.lora_config.spreading_factor;
  config.preamble_len = catsniffer.lora_config.preamble_len;
  config.coding_rate = catsniffer.lora_config.coding_rate;
  config.tx_power = catsniffer.lora_config.tx_power;
  config.tx = false; // <--- RX Mode
  config.iq_inverted = catsniffer.lora_config.iq_inverted;
  config.public_network = false;

  // 1. Aplicar configuración física primero
  int ret = lora_config(lora_dev, &config);
  if (ret < 0)
    return ret;

  // Inject custom Sync Word
  SX126xWriteRegister(0x0740, (catsniffer.lora_config.syncword >> 8) & 0xFF);
  SX126xWriteRegister(0x0741, catsniffer.lora_config.syncword & 0xFF);

  // 2. Iniciar la escucha asíncrona
  return lora_recv_async(lora_dev, lora_rx_cb, NULL);
}

// LoRa thread function
static void lora_thread_func(void *p1, void *p2, void *p3) {
  char command_buffer[128];
  size_t cmd_len = 0;

  while (1) {
    if (k_sem_take(&lora_data_sem, K_MSEC(100)) == 0) {
      // Skip operations if config lock is active
      if (catsniffer.lora_config_lock) {
        k_msleep(10);
        continue;
      }

      // Start async rx
      lora_start_rx_async();
      if (catsniffer.lora_mode == LORA_MODE_COMMAND) {
        // COMMAND MODE: Line-buffered text commands
        uint8_t usb_buf[64];
        int usb_len =
            safe_ring_buf_get(&rb_usb_to_sx1262, usb_buf, sizeof(usb_buf));

        if (usb_len > 0) {
          for (int i = 0; i < usb_len; i++) {
            char c = usb_buf[i];

            if (c == '\n' || c == '\r') {
              if (cmd_len > 0) {
                command_buffer[cmd_len] = '\0';
                process_lora_command(command_buffer);
                cmd_len = 0;
              }
            } else if (cmd_len < sizeof(command_buffer) - 1) {
              command_buffer[cmd_len++] = c;
            }
          }
        }
      } else {
        // STREAM MODE: Raw binary TX/RX
        uint8_t tx_buffer[255];
        int tx_len =
            safe_ring_buf_get(&rb_usb_to_sx1262, tx_buffer, sizeof(tx_buffer));

        if (tx_len > 0 && catsniffer.lora_initialized &&
            !catsniffer.lora_config_lock) {
          // Stop any Rx
          lora_stop_rx();
          // Switch to TX mode, send, then switch
          // back to RX mode
          lora_set_tx_mode();
          lora_send(lora_dev, tx_buffer, tx_len);
          lora_start_rx_async(); // Back to RX
                                 // mode
        }
      }
    }
    // k_msleep(10);
  }
}

int main(void) {
  int ret;
  // Get device references
  uart_cc1352 = CC1352_UART;
  cdc0_dev = CDC0_DEV;
  cdc1_dev = CDC1_DEV;
  cdc2_dev = CDC2_DEV;

  // Initialize GPIO
  INIT_GPIO(pin_reset, GPIO_OUTPUT);
  INIT_GPIO(pin_boot, GPIO_INPUT | GPIO_PULL_UP);
  INIT_GPIO(led0, GPIO_OUTPUT);
  INIT_GPIO(led1, GPIO_OUTPUT);
  INIT_GPIO(led2, GPIO_OUTPUT);
  INIT_GPIO(ctf1, GPIO_OUTPUT);
  INIT_GPIO(ctf2, GPIO_OUTPUT);
  INIT_GPIO(ctf3, GPIO_OUTPUT);

  INIT_GPIO(cjtag0, GPIO_INPUT);
  INIT_GPIO(cjtag1, GPIO_INPUT);
  INIT_GPIO(cjtag2, GPIO_INPUT);
  INIT_GPIO(cjtag3, GPIO_INPUT);

  gpio_pin_set_dt(&pin_reset, 1);

  // Check device readiness
  if (!device_is_ready(cdc0_dev) || !device_is_ready(uart_cc1352)) {
    return -ENODEV;
  }

  // Determine mode
  if (!gpio_pin_get_dt(&pin_boot)) {
    catsniffer.led_interval = 200;
    catsniffer.baud = 500000;
    catsniffer.mode = BOOT;
  } else {
    catsniffer.led_interval = 1000;
    catsniffer.baud = 921600;
    catsniffer.mode = PASSTHROUGH;
  }

  // Initialize LoRa configuration defaults
  catsniffer.lora_mode = LORA_MODE_STREAM;
  catsniffer.lora_config.frequency = 915000000;
  catsniffer.lora_config.spreading_factor = SF_7;
  catsniffer.lora_config.bandwidth = BW_125_KHZ;
  catsniffer.lora_config.coding_rate = CR_4_5;
  catsniffer.lora_config.tx_power = 20;
  catsniffer.lora_config.preamble_len = 12;
  catsniffer.lora_config.iq_inverted = false;
  catsniffer.lora_config.public_network = false;
  catsniffer.lora_config.config_pending = false;
  catsniffer.lora_initialized = false;
  catsniffer.lora_config_lock = false;

  // Timeout for boot pin - don't hang forever
  int timeout = 0;
  while (!gpio_pin_get_dt(&pin_boot) && timeout < 50) {
    k_msleep(10);
    timeout++;
  }

  gpio_pin_set_dt(&led0, 0);
  gpio_pin_set_dt(&led1, 0);
  gpio_pin_set_dt(&led2, 0);

  // Initialize USB
  ret = enable_usb_device_next();
  if (ret < 0) {
    return ret;
  }
  gpio_pin_set_dt(&led0, 1);

  // Initialize ALL ring buffers
  ring_buf_init(&rb_cc1352_to_usb, sizeof(ring_cc1352_to_usb),
                ring_cc1352_to_usb);
  ring_buf_init(&rb_usb_to_cc1352, sizeof(ring_usb_to_cc1352),
                ring_usb_to_cc1352);
  ring_buf_init(&rb_sx1262_to_usb, sizeof(ring_sx1262_to_usb),
                ring_sx1262_to_usb);
  ring_buf_init(&rb_usb_to_sx1262, sizeof(ring_usb_to_sx1262),
                ring_usb_to_sx1262);
  ring_buf_init(&rb_config_to_usb, sizeof(ring_config_to_usb),
                ring_config_to_usb);
  ring_buf_init(&rb_usb_to_config, sizeof(ring_usb_to_config),
                ring_usb_to_config);

  // Configure UART
  struct uart_config uart_cfg;
  uart_config_get(uart_cc1352, &uart_cfg);
  uart_cfg.baudrate = catsniffer.baud;
  uart_configure(uart_cc1352, &uart_cfg);

  // Set up interrupt handlers
  uart_irq_callback_set(cdc0_dev, cdc0_interrupt_handler);
  uart_irq_rx_enable(cdc0_dev);

  // Only set up cdc1 if it exists
  if (cdc1_dev) {
    uart_irq_callback_set(cdc1_dev, cdc1_interrupt_handler);
    uart_irq_rx_enable(cdc1_dev);
  }

  if (cdc2_dev) {
    uart_irq_callback_set(cdc2_dev, cdc2_interrupt_handler);
    uart_irq_rx_enable(cdc2_dev);
  }

  uart_irq_callback_set(uart_cc1352, cc1352_uart_interrupt_handler);
  uart_irq_rx_enable(uart_cc1352);

  reset_cc1352();

  if (catsniffer.mode == BOOT) {
    boot_mode_cc1352();
  } else {
    change_band(GIG);
  }

  // Set initial LED states
  gpio_pin_set_dt(&led0, 0);
  gpio_pin_set_dt(&led1, 0);
  gpio_pin_set_dt(&led2, 0);

  // Send startup message AFTER everything is initialized
  k_msleep(1000); // Wait a moment for USB to be ready
  const char *startup_msg = "Catsniffer Firmware Ready - Config Port\n";
  safe_ring_buf_put(&rb_config_to_usb, (uint8_t *)startup_msg,
                    strlen(startup_msg));
  uart_irq_tx_enable(cdc2_dev);

  const char *lora_welcome = "LoRa Control Port\n";
  safe_ring_buf_put(&rb_sx1262_to_usb, (uint8_t *)lora_welcome,
                    strlen(lora_welcome));
  uart_irq_tx_enable(cdc1_dev);

  ret = initialize_lora();
  if (ret < 0) {
    const char *startup_msg = "LoRa initialization failed\r\n";
    safe_ring_buf_put(&rb_config_to_usb, (uint8_t *)startup_msg,
                      strlen(startup_msg));
    if (cdc2_dev)
      uart_irq_tx_enable(cdc2_dev);
  }

  // Start LoRa thread
  k_thread_create(&lora_thread, lora_thread_stack, LORA_THREAD_STACK_SIZE,
                  lora_thread_func, NULL, NULL, NULL, LORA_THREAD_PRIORITY, 0,
                  K_NO_WAIT);

  // Main loop with LED animation
  while (1) {
    int64_t current_time = k_uptime_get();
    if (current_time - catsniffer.previous_millis > catsniffer.led_interval) {
      catsniffer.previous_millis = current_time;
      // Check catsniffer mode
      if (catsniffer.mode) {
        static int led_index = 0;
        // Cycle through LEDs
        gpio_pin_toggle_dt(LEDs[led_index]);
        led_index++;
        if (led_index > 2)
          led_index = 0;
      } else {
        // Just toggle LED2
        gpio_pin_toggle_dt(&led2);
      }
    }

    k_msleep(10);
  }

  return 0;
}
