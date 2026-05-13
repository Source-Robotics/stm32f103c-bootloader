/* STM32F103C CAN/UART Bootloader — main.h
 * Target: STM32F103CBT6 (128 KB flash, 20 KB SRAM)
 * Bootloader region: 0x08000000 – 0x08002FFF (12 KB)
 * Application base:  0x08003000
 */

#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

#include "stm32f1xx_hal.h"
#include <stdint.h>

/* ---- Flash layout -------------------------------------------------------- */
#define PAGE_SIZE   0x100                          /* 256 words = 1 KB       */
#define PAGE_COUNT  116                            /* (128K-12K)/1K app pages */
#define APP_BASE    ((uint32_t *)0x08003000UL)
#define FLASH_VARS  ((struct bl_vars_t *)(APP_BASE - PAGE_SIZE))

/* ---- Timeouts (ms) ------------------------------------------------------- */
#define STARTUP_TO  2000   /* initial listen window before auto-boot */
#define NOCANRX_TO  3000   /* inactivity window after first valid packet */
#define FLASH_INPROGRESS_TO 60000 /* inactivity window while a flash sequence is in progress */

/* ---- Magic value for fast-path boot -------------------------------------- */
#define MAGIC_VAL   0x36051BF3UL
#define MAGIC_ADDR  ((uint32_t *)(SRAM_BASE + 0x1000))

/* ---- Status LED (PA7 on v170 batch, PB13 on standard — drive both) ------ */
#define LED_ON()     do { HAL_GPIO_WritePin(GPIOA, GPIO_PIN_7,  GPIO_PIN_RESET); \
                          HAL_GPIO_WritePin(GPIOB, GPIO_PIN_13, GPIO_PIN_RESET); } while(0)
#define LED_OFF()    do { HAL_GPIO_WritePin(GPIOA, GPIO_PIN_7,  GPIO_PIN_SET);   \
                          HAL_GPIO_WritePin(GPIOB, GPIO_PIN_13, GPIO_PIN_SET);   } while(0)
#define LED_TOGGLE() do { HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_7);  \
                          HAL_GPIO_TogglePin(GPIOB, GPIO_PIN_13); } while(0)

/* ---- CAN IDs ------------------------------------------------------------- */
#define CANID_BOOTLOADER_CMD   0x700U  /* host -> MCU, 8 bytes */
#define CANID_BOOTLOADER_RPLY  0x701U  /* MCU -> host, 5 bytes (+ board_id offset) */
#define BL_BOARD_ID_MAX        13U     /* IDs 14 and 15 are reserved */

/* ---- UART framing -------------------------------------------------------- */
#define UART_BL_START_BYTE  0xBBU

/* ---- UART command codes -------------------------------------------------- */
#define BL_CMD_PING        0x01U
#define BL_CMD_WRITE_BUF   0x02U  /* par1=word_offset, par2=data_word */
#define BL_CMD_WRITE_PAGE  0x03U  /* par1=page_num,    par2=page_crc32 */
#define BL_CMD_WRITE_CRC   0x04U  /* par1=page_count,  par2=app_crc32  */
#define BL_CMD_SET_ID      0x05U  /* par1=new_board_id */

/* ---- UART command codes (same values as CAN — shared semantics) --------- */
#define UART_BL_CMD_PING          BL_CMD_PING
#define UART_BL_CMD_WRITE_BUF     BL_CMD_WRITE_BUF
#define UART_BL_CMD_WRITE_PAGE    BL_CMD_WRITE_PAGE
#define UART_BL_CMD_WRITE_CRC     BL_CMD_WRITE_CRC
#define UART_BL_CMD_SET_ID        BL_CMD_SET_ID
#define UART_BL_CMD_ERASE_APP     0x06U  /* erase application flash pages */
#define UART_BL_CMD_STREAM_BEGIN  0x07U  /* par1=page_num */
#define UART_BL_CMD_STREAM_STATUS 0x08U  /* par1=last frame index */
#define UART_BL_CMD_STREAM_DATA   0x09U  /* payload=[seq][8 bytes]; fire-and-forget, no reply */
#define UART_WBUF_ACK_STRIDE      1U     /* ACK every WBUF for reliable flow control */
#define UART_STREAM_FRAME_COUNT   128U   /* 128 x 8-byte frames = 1 KB page */

/* ---- CAN command codes (match CAN_Bootloader-main reference scripts) ----- */
#define CAN_BL_CMD_WRITE_BUF   0x01U  /* par1=word_offset, par2=data_word */
#define CAN_BL_CMD_WRITE_PAGE  0x02U  /* par1=page_num,    par2=page_crc32 */
#define CAN_BL_CMD_WRITE_CRC   0x03U  /* par1=page_count,  par2=app_crc32  */
#define CAN_BL_CMD_PING        0x04U
#define CAN_BL_CMD_SET_ID      0x05U  /* par1=new_board_id */
#define CAN_BL_CMD_ERASE_APP   0x06U  /* erase application flash pages */
#define CAN_BL_CMD_STREAM_BEGIN  0x07U  /* par1=page_num */
#define CAN_BL_CMD_STREAM_STATUS 0x08U  /* par1=last 8-byte frame index */
#define CAN_WBUF_ACK_STRIDE    1U     /* ACK every WBUF for reliable flow control */
#define CAN_STREAM_FRAME_COUNT 128U    /* 128 x 8-byte frames = 1 KB page */

/* ---- Error codes --------------------------------------------------------- */
#define BL_SUCCESS              0x00U
#define BL_ERR_INVALID_OFFSET   0x01U
#define BL_ERR_INVALID_CRC      0x02U
#define BL_ERR_FLASH_WRITE      0x03U
#define BL_ERR_INVALID_PAGE_NUM 0x04U

/* ---- Structs ------------------------------------------------------------- */

struct app_vars_t {
    uint32_t page_count;  /* number of 1 KB pages in the application */
    uint32_t crc;         /* CRC32 of the entire application image    */
};

struct board_vars_t {
    uint64_t bl_build_version; /* compile-time UNIX timestamp; resets config on new BL */
    uint8_t  id;               /* board CAN ID (0-13) */
    uint8_t  _padding[3];
};

struct bl_vars_t {             /* stored in flash config page; size must be mult of 4 */
    struct app_vars_t   app;
    struct board_vars_t board;
};

_Static_assert(sizeof(struct bl_vars_t) % 4 == 0, "bl_vars_t size must be a multiple of 4");

/* The host firmware uses an identical struct to read/write this
 * page. If the layout changes here, update the matching static_assert in
 * host Firmware/src/bootloader_config.h, AND vice versa. */
_Static_assert(sizeof(struct bl_vars_t) == 24, "bl_vars_t must be 24 bytes to match host application");

struct __packed bl_cmd_t {
    uint8_t  brd;   /* target board ID (0 = broadcast for ping) */
    uint8_t  cmd;   /* command code */
    uint16_t par1;  /* parameter 1 */
    uint32_t par2;  /* parameter 2 */
};

_Static_assert(sizeof(struct bl_cmd_t) == 8, "bl_cmd_t must be exactly 8 bytes");

static inline uint8_t bl_board_id(void)
{
    uint8_t id = FLASH_VARS->board.id;
    return (id <= BL_BOARD_ID_MAX) ? id : 0U;
}

/* ---- HAL handle externs (defined in main.c) ------------------------------ */
extern CAN_HandleTypeDef  hcan;
extern CRC_HandleTypeDef  hcrc;
extern IWDG_HandleTypeDef hiwdg;
extern UART_HandleTypeDef huart1;

/* ---- Function prototypes ------------------------------------------------- */
void Error_Handler(void);

#ifdef __cplusplus
}
#endif
#endif /* __MAIN_H */
