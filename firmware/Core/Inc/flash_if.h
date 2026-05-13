#ifndef FLASH_IF_H
#define FLASH_IF_H

#include <stdint.h>

/* Write `len` 32-bit words from `buf` to flash page at `page`.
 * Erases the page first. Returns 0 on success, non-zero on error. */
uint8_t fls_wr(const uint32_t *page, const uint32_t *buf, uint32_t len);

/* Erase all application flash pages, preserving the bootloader and config page. */
uint8_t fls_erase_app(void);

#endif /* FLASH_IF_H */
