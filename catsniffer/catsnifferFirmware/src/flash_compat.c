#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include <hardware/flash.h>

#define PAGE_SIZE 256U

/*
 * Compatibility shim for RP2040 Zephyr/Pico SDK combinations where
 * flash_write_partial() is referenced by the flash driver but not provided.
 */
__attribute__((weak)) void flash_write_partial(uint32_t offset,
					       const uint8_t *data, size_t size)
{
	uint32_t page_base = offset & ~(PAGE_SIZE - 1U);
	uint32_t page_offset = offset - page_base;
	uint8_t page_buf[PAGE_SIZE];

	memcpy(page_buf, (const void *)(CONFIG_FLASH_BASE_ADDRESS + page_base),
	       PAGE_SIZE);
	memcpy(&page_buf[page_offset], data, size);
	flash_range_program(page_base, page_buf, PAGE_SIZE);
}
