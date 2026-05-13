/* STM32F103C CAN/UART Bootloader — bootloader (PreSystemInit)
 * Called before HAL_Init() via __attribute__((constructor)) linkage in
 * the startup assembly.  Implements the fast-path SRAM magic check.
 */

#include "bootloader.h"
#include "main.h"
#include "cmsis_gcc.h"   /* __set_MSP */

void PreSystemInit(void)
{
    uint32_t reset_flags = RCC->CSR;

    if (*(MAGIC_ADDR) == MAGIC_VAL)
    {
        /* Only honor the fast-path after the software reset issued by the bootloader. */
        if ((reset_flags & RCC_CSR_SFTRSTF) == 0U)
        {
            *(MAGIC_ADDR) = 0;
            RCC->CSR |= RCC_CSR_RMVF;
            return;
        }

        uint32_t app_sp  = *(APP_BASE);
        uint32_t app_rst = *(APP_BASE + 1);

        /* Validate: SP must be in SRAM, reset vector must be in app flash */
        if ((app_sp  >= 0x20000000UL) && (app_sp  <= 0x20005000UL) &&
            (app_rst >= 0x08003001UL) && (app_rst <= 0x0801FFFFUL))
        {
            *(MAGIC_ADDR) = 0;
            __set_MSP(app_sp);
            __asm volatile ("bx %0\n" :: "r" (app_rst) :);
        }
        /* Validation failed — clear magic and fall through to bootloader */
        *(MAGIC_ADDR) = 0;
    }

    RCC->CSR |= RCC_CSR_RMVF;
}
