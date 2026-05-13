#ifndef CAN_BL_H
#define CAN_BL_H

#include "stm32f1xx_hal.h"

/* Called from USB_LP_CAN1_RX0_IRQHandler — reads the frame and processes it. */
void can_bl_irq(CAN_HandleTypeDef *pcan);

/* Returns 1 if at least one valid CAN BL packet has been received. */
uint8_t can_bl_message_received(void);

/* Returns HAL_GetTick() timestamp of the last received CAN BL packet. */
uint32_t can_bl_last_rx_tick(void);

/* Returns 1 while a flash sequence is in progress (WBUF/WPAGE seen, WCRC not yet succeeded). */
uint8_t can_bl_flash_in_progress(void);

/* HAL RX FIFO0 callback — register with HAL_CAN_RegisterCallback. */
void can_bl_irq_callback(CAN_HandleTypeDef *pcan);

#endif /* CAN_BL_H */
