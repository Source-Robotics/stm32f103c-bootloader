/* STM32F103C CAN/UART Bootloader — stm32f1xx_hal_msp.c
 * HAL MSP (MCU Support Package) — GPIO, NVIC, and clock init for CAN + USART1.
 *
 * CAN:   PB8 (RX), PB9 (TX)  — CAN_REMAP[1:0]=10 in AFIO_MAPR
 * UART:  PB6 (TX), PB7 (RX)  — USART1_REMAP=1   in AFIO_MAPR
 */

#include "main.h"

void HAL_CRC_MspInit(CRC_HandleTypeDef *hcrc)
{
    __HAL_RCC_CRC_CLK_ENABLE();
}

void HAL_CRC_MspDeInit(CRC_HandleTypeDef *hcrc)
{
    __HAL_RCC_CRC_CLK_DISABLE();
}

void HAL_CAN_MspInit(CAN_HandleTypeDef *hcan)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    /* Enable clocks: CAN1, GPIOB, AFIO */
    __HAL_RCC_CAN1_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_AFIO_CLK_ENABLE();

    /* Remap CAN to PB8 (RX) / PB9 (TX) — CAN_REMAP = 10 */
    __HAL_AFIO_REMAP_CAN1_2();

    /* PB8 — CAN_RX: input floating */
    GPIO_InitStruct.Pin  = GPIO_PIN_8;
    GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

    /* PB9 — CAN_TX: alternate function push-pull */
    GPIO_InitStruct.Pin   = GPIO_PIN_9;
    GPIO_InitStruct.Mode  = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
    HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

    /* Enable CAN RX0 interrupt (USB_LP_CAN1_RX0 shares the IRQ on STM32F103) */
    HAL_NVIC_SetPriority(USB_LP_CAN1_RX0_IRQn, 0, 0);
    HAL_NVIC_EnableIRQ(USB_LP_CAN1_RX0_IRQn);
}

void HAL_CAN_MspDeInit(CAN_HandleTypeDef *hcan)
{
    __HAL_RCC_CAN1_FORCE_RESET();
    __HAL_RCC_CAN1_RELEASE_RESET();
    HAL_GPIO_DeInit(GPIOB, GPIO_PIN_8 | GPIO_PIN_9);
    HAL_NVIC_DisableIRQ(USB_LP_CAN1_RX0_IRQn);
}

void HAL_UART_MspInit(UART_HandleTypeDef *huart)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    if (huart->Instance != USART1)
        return;

    /* Enable clocks: USART1, GPIOB, AFIO */
    __HAL_RCC_USART1_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_AFIO_CLK_ENABLE();

    /* Remap USART1 to PB6 (TX) / PB7 (RX) — USART1_REMAP = 1 */
    __HAL_AFIO_REMAP_USART1_ENABLE();

    /* PB6 — USART1_TX: alternate function push-pull */
    GPIO_InitStruct.Pin   = GPIO_PIN_6;
    GPIO_InitStruct.Mode  = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
    HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

    /* PB7 — USART1_RX: input floating */
    GPIO_InitStruct.Pin  = GPIO_PIN_7;
    GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

    /* Enable USART1 interrupt for byte-at-a-time RX */
    HAL_NVIC_SetPriority(USART1_IRQn, 1, 0);
    HAL_NVIC_EnableIRQ(USART1_IRQn);
}

void HAL_UART_MspDeInit(UART_HandleTypeDef *huart)
{
    if (huart->Instance != USART1)
        return;
    __HAL_RCC_USART1_FORCE_RESET();
    __HAL_RCC_USART1_RELEASE_RESET();
    HAL_GPIO_DeInit(GPIOB, GPIO_PIN_6 | GPIO_PIN_7);
    HAL_NVIC_DisableIRQ(USART1_IRQn);
}
