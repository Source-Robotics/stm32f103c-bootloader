/* STM32F103C CAN/UART Bootloader — uart_bl.c
 * UART receive state machine + bootloader command processing.
 * Transport: USART1 remapped to PB6 (TX) / PB7 (RX) @ 256 000 bps, 8N1.
 *
 * Frame format (host → MCU):
 *   [0xBB][CMD][LEN_L][LEN_H][BOARD_ID][DATA...][CRC16_L][CRC16_H]
 *   CRC16/CCITT over bytes [CMD..DATA end]
 *
 * Response (MCU → host, 3 bytes):
 *   [board_id][cmd][error_code]
 */

#include "uart_bl.h"
#include "main.h"
#include "flash_if.h"
#include <string.h>

/* ---- CRC-16/CCITT (poly 0x1021, init 0xFFFF) ----------------------------- */
static uint16_t crc16_update(uint16_t crc, uint8_t byte)
{
    crc ^= (uint16_t)byte << 8;
    for (int i = 0; i < 8; i++)
        crc = (crc & 0x8000U) ? ((crc << 1) ^ 0x1021U) : (crc << 1);
    return crc;
}

/* ---- RX state machine ----------------------------------------------------- */
typedef enum {
    RX_IDLE,
    RX_CMD,
    RX_LEN_L,
    RX_LEN_H,
    RX_BOARD_ID,
    RX_DATA,
    RX_CRC_L,
    RX_CRC_H,
} rx_state_t;

#define UART_MAX_PAYLOAD 16 /* longest payload is STREAM_DATA: 1 (seq) + 8 (data) = 9 bytes */

static rx_state_t s_rx_state    = RX_IDLE;
static uint8_t    s_cmd         = 0;
static uint16_t   s_len         = 0;
static uint8_t    s_board_id    = 0;
static uint8_t    s_data[UART_MAX_PAYLOAD];
static uint16_t   s_data_idx    = 0;
static uint16_t   s_crc_rx      = 0;
static uint16_t   s_crc_calc    = 0;

static volatile uint8_t s_message_received = 0;
static volatile uint32_t s_lastuartrx      = 0;
static volatile uint32_t s_last_uart_byte_tick = 0;
static volatile uint8_t s_flash_in_progress = 0;

static uint32_t   s_pagebuf[PAGE_SIZE];  /* reuse across writes */

/* Stream-mode state (mirrors CAN streaming protocol) */
static uint8_t  s_stream_active = 0U;
static uint16_t s_stream_page = 0U;
static uint32_t s_stream_rx_mask[4]; /* 128 bits: one per 8-byte stream frame */

static uint8_t stream_frame_seen(uint8_t seq)
{
    return (s_stream_rx_mask[seq / 32U] & (1UL << (seq % 32U))) ? 1U : 0U;
}

static void stream_mark_frame_seen(uint8_t seq)
{
    s_stream_rx_mask[seq / 32U] |= (1UL << (seq % 32U));
}

static uint8_t stream_range_complete(uint8_t end_seq)
{
    for (uint8_t seq = 0; seq <= end_seq; seq++)
    {
        if (!stream_frame_seen(seq))
            return 0U;
    }
    return 1U;
}

static void uart_bl_mark_activity(void)
{
    s_message_received = 1;
    s_lastuartrx = HAL_GetTick();
}

void uart_bl_reset_parser(void)
{
    s_rx_state = RX_IDLE;
    s_len = 0;
    s_data_idx = 0;
    s_crc_rx = 0;
    s_crc_calc = 0;
}

/* ---- Transmit helpers ----------------------------------------------------- */
static void uart_tx(const uint8_t *buf, uint16_t len)
{
    HAL_UART_Transmit(&huart1, (uint8_t *)buf, len, 10);
}

/* Reply now includes par1 so the host can correlate responses to specific
 * commands and ignore late/stale responses. */
static void uart_tx_resp(uint8_t cmd, uint8_t ec, uint16_t par1)
{
    uint8_t resp[5] = { bl_board_id(), cmd, ec,
                        (uint8_t)(par1 & 0xFFU),
                        (uint8_t)((par1 >> 8) & 0xFFU) };
    uart_tx(resp, 5);
}

/* ---- Command processing --------------------------------------------------- */
static void process_uart_cmd(void)
{
    uart_bl_mark_activity();

    /* Ping: any board responds */
    if (s_cmd == UART_BL_CMD_PING)
    {
        uart_tx_resp(UART_BL_CMD_PING, BL_SUCCESS, 0U);
        return;
    }

    /* All other commands: must be addressed to this board */
    if (s_board_id != bl_board_id())
        return;

    switch (s_cmd)
    {
    /* WRITE_BUF payload: [offset_L][offset_H][data0][data1][data2][data3] */
    case UART_BL_CMD_WRITE_BUF:
    {
        s_flash_in_progress = 1;
        s_stream_active = 0U;
        if (s_len != 6) { uart_tx_resp(s_cmd, BL_ERR_INVALID_OFFSET, 0U); break; }
        uint16_t offset = (uint16_t)s_data[0] | ((uint16_t)s_data[1] << 8);
        uint32_t word   = (uint32_t)s_data[2]
                        | ((uint32_t)s_data[3] << 8)
                        | ((uint32_t)s_data[4] << 16)
                        | ((uint32_t)s_data[5] << 24);
        if (offset < PAGE_SIZE)
        {
            s_pagebuf[offset] = word;
#if UART_WBUF_ACK_STRIDE > 0U
            if (((offset + 1U) % UART_WBUF_ACK_STRIDE) == 0U)
            {
                uart_tx_resp(s_cmd, BL_SUCCESS, offset);
            }
#endif
        }
        else
        {
            uart_tx_resp(s_cmd, BL_ERR_INVALID_OFFSET, offset);
        }
        break;
    }

    /* WRITE_PAGE payload: [page_L][page_H][crc32 LE, 4 bytes] */
    case UART_BL_CMD_WRITE_PAGE:
    {
        s_flash_in_progress = 1;
        if (s_len != 6) { uart_tx_resp(s_cmd, BL_ERR_INVALID_PAGE_NUM, 0U); break; }
        uint16_t page = (uint16_t)s_data[0] | ((uint16_t)s_data[1] << 8);
        uint32_t crc  = (uint32_t)s_data[2]
                      | ((uint32_t)s_data[3] << 8)
                      | ((uint32_t)s_data[4] << 16)
                      | ((uint32_t)s_data[5] << 24);
        if (page < PAGE_COUNT)
        {
            uint32_t computed = HAL_CRC_Calculate(&hcrc, s_pagebuf, PAGE_SIZE);
            if (computed == crc)
            {
                uint32_t pgofs = page * PAGE_SIZE;
                uint8_t r = fls_wr(APP_BASE + pgofs, s_pagebuf, PAGE_SIZE);
                if (r == 0U) s_stream_active = 0U;
                uart_tx_resp(s_cmd, r ? BL_ERR_FLASH_WRITE : BL_SUCCESS, page);
            }
            else
            {
                uart_tx_resp(s_cmd, BL_ERR_INVALID_CRC, page);
            }
        }
        else
        {
            uart_tx_resp(s_cmd, BL_ERR_INVALID_PAGE_NUM, page);
        }
        break;
    }

    /* ERASE_APP: no payload required */
    case UART_BL_CMD_ERASE_APP:
    {
        s_flash_in_progress = 1;
        s_stream_active = 0U;
        uint8_t r = fls_erase_app();
        uart_tx_resp(s_cmd, r ? BL_ERR_FLASH_WRITE : BL_SUCCESS, 0U);
        break;
    }

    /* STREAM_BEGIN payload: [page_L][page_H] */
    case UART_BL_CMD_STREAM_BEGIN:
    {
        s_flash_in_progress = 1;
        if (s_len != 2) { uart_tx_resp(s_cmd, BL_ERR_INVALID_PAGE_NUM, 0U); break; }
        uint16_t page = (uint16_t)s_data[0] | ((uint16_t)s_data[1] << 8);
        if (page < PAGE_COUNT)
        {
            s_stream_active = 1U;
            s_stream_page = page;
            memset(s_pagebuf, 0xFF, sizeof(s_pagebuf));
            memset(s_stream_rx_mask, 0, sizeof(s_stream_rx_mask));
            uart_tx_resp(s_cmd, BL_SUCCESS, page);
        }
        else
        {
            uart_tx_resp(s_cmd, BL_ERR_INVALID_PAGE_NUM, page);
        }
        break;
    }

    /* STREAM_DATA payload: [seq][D0..D7] (9 bytes). Fire-and-forget — NO REPLY. */
    case UART_BL_CMD_STREAM_DATA:
    {
        if (s_len != 9 || !s_stream_active) break;
        uint8_t seq = s_data[0];
        if (seq < UART_STREAM_FRAME_COUNT)
        {
            s_flash_in_progress = 1;
            memcpy(&s_pagebuf[seq * 2U], &s_data[1], 8);
            stream_mark_frame_seen(seq);
        }
        /* No uart_tx_resp — host correlates via STREAM_STATUS. */
        break;
    }

    /* STREAM_STATUS payload: [end_seq_L][end_seq_H]. Returns OK iff all
     * frames 0..end_seq have been seen. */
    case UART_BL_CMD_STREAM_STATUS:
    {
        if (s_len != 2) { uart_tx_resp(s_cmd, BL_ERR_INVALID_OFFSET, 0U); break; }
        uint16_t end_seq = (uint16_t)s_data[0] | ((uint16_t)s_data[1] << 8);
        if (!s_stream_active)
        {
            uart_tx_resp(s_cmd, BL_ERR_INVALID_PAGE_NUM, end_seq);
        }
        else if ((end_seq >= UART_STREAM_FRAME_COUNT) || (s_stream_page >= PAGE_COUNT))
        {
            uart_tx_resp(s_cmd, BL_ERR_INVALID_OFFSET, end_seq);
        }
        else
        {
            uint8_t ok = stream_range_complete((uint8_t)end_seq);
            uart_tx_resp(s_cmd, ok ? BL_SUCCESS : BL_ERR_INVALID_CRC, end_seq);
        }
        break;
    }

    /* WRITE_CRC payload: [count_L][count_H][crc32 LE, 4 bytes] */
    case UART_BL_CMD_WRITE_CRC:
    {
        if (s_len != 6) { uart_tx_resp(s_cmd, BL_ERR_INVALID_PAGE_NUM, 0U); break; }
        uint16_t count = (uint16_t)s_data[0] | ((uint16_t)s_data[1] << 8);
        uint32_t crc   = (uint32_t)s_data[2]
                       | ((uint32_t)s_data[3] << 8)
                       | ((uint32_t)s_data[4] << 16)
                       | ((uint32_t)s_data[5] << 24);
        if (count <= PAGE_COUNT)
        {
            uint32_t computed = HAL_CRC_Calculate(&hcrc, (uint32_t *)APP_BASE,
                                                  count * PAGE_SIZE);
            if (computed == crc)
            {
                struct bl_vars_t vars;
                vars.app.page_count = count;
                vars.app.crc        = crc;
                vars.board          = FLASH_VARS->board;
                uint8_t r = fls_wr(APP_BASE - PAGE_SIZE, (uint32_t *)&vars,
                                   sizeof(vars) / 4);
                if (r == 0U) s_flash_in_progress = 0;
                uart_tx_resp(s_cmd, r ? BL_ERR_FLASH_WRITE : BL_SUCCESS, count);
            }
            else
            {
                uart_tx_resp(s_cmd, BL_ERR_INVALID_CRC, count);
            }
        }
        else
        {
            uart_tx_resp(s_cmd, BL_ERR_INVALID_PAGE_NUM, count);
        }
        break;
    }

    /* SET_ID payload: [new_id] */
    case UART_BL_CMD_SET_ID:
    {
        if (s_len != 1) { uart_tx_resp(s_cmd, BL_ERR_INVALID_PAGE_NUM, 0U); break; }
        uint8_t new_id = s_data[0];
        if (new_id <= BL_BOARD_ID_MAX)
        {
            struct bl_vars_t vars = *FLASH_VARS;
            vars.board.id = new_id;
            uint8_t r = fls_wr(APP_BASE - PAGE_SIZE, (uint32_t *)&vars,
                               sizeof(vars) / 4);
            uart_tx_resp(s_cmd, r ? BL_ERR_FLASH_WRITE : BL_SUCCESS, new_id);
        }
        else
        {
            uart_tx_resp(s_cmd, BL_ERR_INVALID_PAGE_NUM, new_id);
        }
        break;
    }

    default:
        break;
    }
}

/* ---- Public ISR feed ------------------------------------------------------- */
void uart_bl_rx_byte(uint8_t byte)
{
    uint32_t now = HAL_GetTick();

    s_message_received = 1;
    s_lastuartrx = now;

    if ((s_rx_state != RX_IDLE) && ((now - s_last_uart_byte_tick) > 20U))
    {
        s_rx_state = RX_IDLE;
    }
    s_last_uart_byte_tick = now;

    switch (s_rx_state)
    {
    case RX_IDLE:
        if (byte == UART_BL_START_BYTE)
        {
            s_crc_calc = 0xFFFFU;
            s_rx_state = RX_CMD;
        }
        break;

    case RX_CMD:
        s_cmd      = byte;
        s_crc_calc = crc16_update(s_crc_calc, byte);
        s_rx_state = RX_LEN_L;
        break;

    case RX_LEN_L:
        s_len      = byte;
        s_crc_calc = crc16_update(s_crc_calc, byte);
        s_rx_state = RX_LEN_H;
        break;

    case RX_LEN_H:
        s_len     |= (uint16_t)byte << 8;
        s_crc_calc = crc16_update(s_crc_calc, byte);
        if (s_len > UART_MAX_PAYLOAD)
        {
            uart_bl_reset_parser();
            break;
        }
        s_rx_state = RX_BOARD_ID;
        break;

    case RX_BOARD_ID:
        s_board_id = byte;
        s_crc_calc = crc16_update(s_crc_calc, byte);
        s_data_idx = 0;
        s_rx_state = (s_len > 0) ? RX_DATA : RX_CRC_L;
        break;

    case RX_DATA:
        if (s_data_idx < UART_MAX_PAYLOAD)
            s_data[s_data_idx] = byte;
        s_crc_calc = crc16_update(s_crc_calc, byte);
        if (++s_data_idx >= s_len)
            s_rx_state = RX_CRC_L;
        break;

    case RX_CRC_L:
        s_crc_rx   = byte;
        s_rx_state = RX_CRC_H;
        break;

    case RX_CRC_H:
        s_crc_rx  |= (uint16_t)byte << 8;
        if (s_crc_rx == s_crc_calc)
            process_uart_cmd();
        /* always reset — ignore malformed frames */
        s_rx_state = RX_IDLE;
        break;
    }
}

uint8_t uart_bl_message_received(void)
{
    return s_message_received;
}

uint32_t uart_bl_last_rx_tick(void)
{
    return s_lastuartrx;
}

uint8_t uart_bl_flash_in_progress(void)
{
    return s_flash_in_progress;
}
