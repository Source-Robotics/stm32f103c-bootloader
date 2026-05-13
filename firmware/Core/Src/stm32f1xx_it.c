/* STM32F103C CAN/UART Bootloader — stm32f1xx_it.c
 * ISR handler implementations.
 */

#include "stm32f1xx_it.h"
#include "main.h"
#include "can_bl.h"
#include "uart_bl.h"

void NMI_Handler(void)          { while (1) {} }
void HardFault_Handler(void)    { while (1) {} }
void MemManage_Handler(void)    { while (1) {} }
void BusFault_Handler(void)     { while (1) {} }
void UsageFault_Handler(void)   { while (1) {} }
void SVC_Handler(void)          {}
void DebugMon_Handler(void)     {}
void PendSV_Handler(void)       {}
void SysTick_Handler(void)      { HAL_IncTick(); }

/* CAN RX FIFO0 message pending — also shared with USB_LP on STM32F103 */
void USB_LP_CAN1_RX0_IRQHandler(void)
{
    HAL_CAN_IRQHandler(&hcan);
}

/* USART1 — byte-at-a-time RX */
void USART1_IRQHandler(void)
{
    uint32_t sr = huart1.Instance->SR;

    if ((sr & (USART_SR_ORE | USART_SR_FE | USART_SR_NE | USART_SR_PE)) != 0U)
    {
        volatile uint32_t clear;
        clear = huart1.Instance->SR;
        clear = huart1.Instance->DR;
        (void)clear;
        uart_bl_reset_parser();
        return;
    }

    /* Read the received byte and feed it to the UART state machine */
    if ((sr & USART_SR_RXNE) != 0U)
    {
        uint8_t byte = (uint8_t)(huart1.Instance->DR & 0xFFU);
        uart_bl_rx_byte(byte);
    }
}
