/*
 * Copyright (c) 2023 Nordic Semiconductor ASA.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef ZEPHYR_SUBSYS_USBD_H
#define ZEPHYR_SUBSYS_USBD_H

#include <stdint.h>
#include <zephyr/usb/usbd.h>

/*
 * This function uses Kconfig.sample_usbd options to configure and initialize a
 * USB device. It configures sample's device context, default string
 * descriptors, USB device configuration, registers any available class
 * instances, and finally initializes USB device. It is limited to a single
 * device with a single configuration instantiated in sample_usbd_init.c, which
 * should be enough for a simple USB device sample.
 *
 * It returns the configured and initialized USB device context on success,
 * otherwise it returns NULL.
 */
struct usbd_context *usbd_init_device(usbd_msg_cb_t msg_cb);

/*
 * This function is similar to sample_usbd_init_device(), but does not
 * initialize the device. It allows the application to set additional features,
 * such as additional descriptors.
 */
struct usbd_context *usbd_setup_device(usbd_msg_cb_t msg_cb);

#endif /* ZEPHYR_SAMPLES_SUBSYS_USB_COMMON_SAMPLE_USBD_H */
