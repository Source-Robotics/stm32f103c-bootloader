#ifndef BOOTLOADER_H
#define BOOTLOADER_H

/* Called before HAL_Init() from Reset_Handler via early_init attribute.
 * Checks SRAM magic value — if present, clears it and jumps directly to app.
 * This is the fast-path boot that skips all peripheral initialisation. */
void PreSystemInit(void);

#endif /* BOOTLOADER_H */
