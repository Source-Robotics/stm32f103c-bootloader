/* STM32F103C CAN/UART Bootloader — flash_if.c
 * Flash erase/write abstraction for STM32F103CBT6.
 * All flash operations in the bootloader go through fls_wr().
 */

#include "flash_if.h"
#include "main.h"
#include "stm32f1xx_hal.h"
#include <string.h>

/* --------------------------------------------------------------------------
 * __fls_wr — low-level: erase one 1 KB page then program `len` 32-bit words.
 * Returns 0 on success, non-zero on HAL error.
 * ---------------------------------------------------------------------- */
static uint8_t __fls_wr(const uint32_t *page, const uint32_t *buf, uint32_t len)
{
    __HAL_FLASH_CLEAR_FLAG(FLASH_FLAG_EOP | FLASH_FLAG_PGERR | FLASH_FLAG_WRPERR);

    uint32_t erase_err;
    FLASH_EraseInitTypeDef erase_cfg = {
        .TypeErase = FLASH_TYPEERASE_PAGES,
        .Banks     = FLASH_BANK_1,
        .PageAddress = (uint32_t)page,
        .NbPages   = 1
    };
    if (HAL_FLASHEx_Erase(&erase_cfg, &erase_err) != HAL_OK)
        return 1;

    for (uint32_t i = 0; i < len; ++i)
    {
        if (HAL_FLASH_Program(FLASH_TYPEPROGRAM_WORD, (uint32_t)(page + i), buf[i]) != HAL_OK)
            return 2;
    }

    return 0;
}

/* --------------------------------------------------------------------------
 * fls_wr - public wrapper: always erase/program, then verify.
 * Returns 0 on success.
 * ---------------------------------------------------------------------- */
uint8_t fls_wr(const uint32_t *page, const uint32_t *buf, uint32_t len)
{
    HAL_FLASH_Unlock();
    uint8_t r = __fls_wr(page, buf, len);
    HAL_FLASH_Lock();
    if (r)
        return r;

    /* Verify */
    if (0 != memcmp(page, buf, 4 * len))
        return 10;

    return 0;
}

uint8_t fls_erase_app(void)
{
    HAL_FLASH_Unlock();

    for (uint32_t page = 0; page < PAGE_COUNT; page++)
    {
        __HAL_FLASH_CLEAR_FLAG(FLASH_FLAG_EOP | FLASH_FLAG_PGERR | FLASH_FLAG_WRPERR);

        uint32_t erase_err;
        FLASH_EraseInitTypeDef erase_cfg = {
            .TypeErase   = FLASH_TYPEERASE_PAGES,
            .Banks       = FLASH_BANK_1,
            .PageAddress = (uint32_t)(APP_BASE + (page * PAGE_SIZE)),
            .NbPages     = 1
        };

        HAL_IWDG_Refresh(&hiwdg);
        if (HAL_FLASHEx_Erase(&erase_cfg, &erase_err) != HAL_OK)
        {
            HAL_FLASH_Lock();
            return 1;
        }

        const uint32_t *page_base = APP_BASE + (page * PAGE_SIZE);
        for (uint32_t i = 0; i < PAGE_SIZE; i++)
        {
            if (page_base[i] != 0xFFFFFFFFUL)
            {
                HAL_FLASH_Lock();
                return 2;
            }
        }
        HAL_IWDG_Refresh(&hiwdg);
    }

    HAL_FLASH_Lock();
    return 0;
}
