#ifndef UART_BL_H
#define UART_BL_H

#include "stm32f1xx_hal.h"

/* Called from USART1_IRQHandler — feeds the byte into the RX state machine. */
void uart_bl_rx_byte(uint8_t byte);
void uart_bl_reset_parser(void);

/* Returns 1 if at least one valid UART BL packet has been received. */
uint8_t uart_bl_message_received(void);

/* Returns HAL_GetTick() timestamp of the last received UART BL packet. */
uint32_t uart_bl_last_rx_tick(void);

/* Returns 1 while a flash sequence is in progress (WBUF/WPAGE seen, WCRC not yet succeeded). */
uint8_t uart_bl_flash_in_progress(void);

#endif /* UART_BL_H */
