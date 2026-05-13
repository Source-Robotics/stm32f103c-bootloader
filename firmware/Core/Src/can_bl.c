/* STM32F103C CAN/UART Bootloader — can_bl.c
 * CAN receive ISR + bootloader command processing.
 * CAN IDs: 0x700 (cmd, 8 bytes) -> 0x701+board_id (reply, 5 bytes)
 * Baud rate: 1 Mbit/s, matching the host application.
 */

#include "can_bl.h"
#include "main.h"
#include "flash_if.h"
#include <string.h>

static volatile uint8_t  s_message_received = 0;
static volatile uint32_t s_lastcanrx        = 0;
static volatile uint8_t  s_flash_in_progress = 0;

static uint8_t can_stream_board_id(uint16_t std_id)
{
    return (uint8_t)((std_id >> 7) & 0x0FU);
}

static uint8_t can_stream_seq(uint16_t std_id)
{
    return (uint8_t)(std_id & 0x7FU);
}

static uint8_t stream_frame_seen(const uint32_t rx_mask[], uint8_t seq)
{
    return (rx_mask[seq / 32U] & (1UL << (seq % 32U))) ? 1U : 0U;
}

static void stream_mark_frame_seen(uint32_t rx_mask[], uint8_t seq)
{
    rx_mask[seq / 32U] |= (1UL << (seq % 32U));
}

static uint8_t stream_range_complete(const uint32_t rx_mask[], uint8_t end_seq)
{
    for (uint8_t seq = 0; seq <= end_seq; seq++)
    {
        if (!stream_frame_seen(rx_mask, seq))
            return 0U;
    }
    return 1U;
}

static void can_bl_mark_activity(void)
{
    s_message_received = 1;
    s_lastcanrx = HAL_GetTick();
}

/* --------------------------------------------------------------------------
 * bl_can_tx_resp - send a 5-byte bootloader reply frame.
 * ---------------------------------------------------------------------- */
/* Reply frame includes par1 so host can match responses to specific commands
 * and not confuse late responses for new ones. CAN WBUF replies are used as
 * flow-control checkpoints; WRITE_PAGE is the full-page CRC/flash ACK. */
static void bl_can_tx_resp(uint8_t cmd, uint8_t ec, uint16_t par1)
{
    uint8_t board_id = bl_board_id();
    CAN_TxHeaderTypeDef m = {0};
    m.IDE   = CAN_ID_STD;
    m.StdId = CANID_BOOTLOADER_RPLY + board_id;
    m.RTR   = CAN_RTR_DATA;
    m.DLC   = 5;
    m.TransmitGlobalTime = DISABLE;
    uint8_t data[8] = { board_id, cmd, ec,
                        (uint8_t)(par1 & 0xFFU),
                        (uint8_t)((par1 >> 8) & 0xFFU),
                        0, 0, 0 };
    uint32_t mailbox;

    for (uint32_t retry = 0; retry < 1000U; retry++)
    {
        if (HAL_CAN_AddTxMessage(&hcan, &m, data, &mailbox) == HAL_OK)
        {
            return;
        }
    }
}

/* --------------------------------------------------------------------------
 * process_can_msg — decode and execute one bootloader command frame.
 * ---------------------------------------------------------------------- */
static void process_can_msg(CAN_RxHeaderTypeDef *msg, uint8_t data[])
{
    static uint32_t pagebuf[PAGE_SIZE];  /* 1 KB page buffer (on stack would overflow) */
    static uint32_t stream_rx_mask[4];    /* 128 bits: one per 8-byte stream frame */
    static uint8_t  stream_active = 0U;
    static uint16_t stream_page = 0U;

    if ((msg->StdId != CANID_BOOTLOADER_CMD) && stream_active && (msg->DLC == 8))
    {
        uint8_t board_id = can_stream_board_id((uint16_t)msg->StdId);
        uint8_t seq = can_stream_seq((uint16_t)msg->StdId);
        if ((board_id == bl_board_id()) && (seq < CAN_STREAM_FRAME_COUNT))
        {
            can_bl_mark_activity();
            s_flash_in_progress = 1;
            memcpy(&pagebuf[seq * 2U], data, 8);
            stream_mark_frame_seen(stream_rx_mask, seq);
        }
        return;
    }

    if ((msg->StdId != CANID_BOOTLOADER_CMD) || (msg->DLC != 8))
        return;

    struct bl_cmd_t blc;
    memcpy(&blc, data, 8);

    if ((blc.cmd != CAN_BL_CMD_PING) &&
        (blc.cmd != CAN_BL_CMD_WRITE_BUF) &&
        (blc.cmd != CAN_BL_CMD_WRITE_PAGE) &&
        (blc.cmd != CAN_BL_CMD_WRITE_CRC) &&
        (blc.cmd != CAN_BL_CMD_SET_ID) &&
        (blc.cmd != CAN_BL_CMD_ERASE_APP) &&
        (blc.cmd != CAN_BL_CMD_STREAM_BEGIN) &&
        (blc.cmd != CAN_BL_CMD_STREAM_STATUS))
    {
        return;
    }

    /* Ping: all boards respond regardless of board ID */
    if (blc.cmd == CAN_BL_CMD_PING)
    {
        can_bl_mark_activity();
        bl_can_tx_resp(CAN_BL_CMD_PING, BL_SUCCESS, blc.par1);
        return;
    }

    /* All other commands: addressed to this board only */
    if (blc.brd != bl_board_id())
        return;

    can_bl_mark_activity();

    switch (blc.cmd)
    {
    /* ---- WRITE_BUF: par1=word_offset, par2=data_word ------------------- */
    case CAN_BL_CMD_WRITE_BUF:
        s_flash_in_progress = 1;
        stream_active = 0U;
        if (blc.par1 < PAGE_SIZE)
        {
            pagebuf[blc.par1] = blc.par2;
#if CAN_WBUF_ACK_STRIDE > 0U
            if (((blc.par1 + 1U) % CAN_WBUF_ACK_STRIDE) == 0U)
            {
                bl_can_tx_resp(CAN_BL_CMD_WRITE_BUF, BL_SUCCESS, blc.par1);
            }
#endif
        }
        else
        {
            bl_can_tx_resp(CAN_BL_CMD_WRITE_BUF, BL_ERR_INVALID_OFFSET, blc.par1);
        }
        break;

    /* ---- WRITE_PAGE: par1=page_num, par2=page_crc32 -------------------- */
    case CAN_BL_CMD_WRITE_PAGE:
        s_flash_in_progress = 1;
        if (blc.par1 < PAGE_COUNT)
        {
            uint32_t crc = HAL_CRC_Calculate(&hcrc, pagebuf, PAGE_SIZE);
            if (crc == blc.par2)
            {
                uint32_t pgofs = blc.par1 * PAGE_SIZE;
                uint8_t r = fls_wr(APP_BASE + pgofs, pagebuf, PAGE_SIZE);
                if (r == 0U) stream_active = 0U;
                bl_can_tx_resp(CAN_BL_CMD_WRITE_PAGE, r ? BL_ERR_FLASH_WRITE : BL_SUCCESS, blc.par1);
            }
            else
            {
                bl_can_tx_resp(CAN_BL_CMD_WRITE_PAGE, BL_ERR_INVALID_CRC, blc.par1);
            }
        }
        else
        {
            bl_can_tx_resp(CAN_BL_CMD_WRITE_PAGE, BL_ERR_INVALID_PAGE_NUM, blc.par1);
        }
        break;

    /* ---- WRITE_CRC: par1=page_count, par2=app_crc32 -------------------- */
    case CAN_BL_CMD_WRITE_CRC:
        if (blc.par1 <= PAGE_COUNT)
        {
            uint32_t crc = HAL_CRC_Calculate(&hcrc, (uint32_t *)APP_BASE,
                                             blc.par1 * PAGE_SIZE);
            if (crc == blc.par2)
            {
                struct bl_vars_t vars;
                vars.app.page_count        = blc.par1;
                vars.app.crc               = blc.par2;
                vars.board                 = FLASH_VARS->board;
                uint8_t r = fls_wr(APP_BASE - PAGE_SIZE, (uint32_t *)&vars,
                                   sizeof(vars) / 4);
                if (r == 0U) s_flash_in_progress = 0;
                bl_can_tx_resp(CAN_BL_CMD_WRITE_CRC, r ? BL_ERR_FLASH_WRITE : BL_SUCCESS, blc.par1);
            }
            else
            {
                bl_can_tx_resp(CAN_BL_CMD_WRITE_CRC, BL_ERR_INVALID_CRC, blc.par1);
            }
        }
        else
        {
            bl_can_tx_resp(CAN_BL_CMD_WRITE_CRC, BL_ERR_INVALID_PAGE_NUM, blc.par1);
        }
        break;

    /* ---- ERASE_APP: erase all application pages -------------------------- */
    case CAN_BL_CMD_ERASE_APP:
    {
        s_flash_in_progress = 1;
        stream_active = 0U;
        uint8_t r = fls_erase_app();
        bl_can_tx_resp(CAN_BL_CMD_ERASE_APP, r ? BL_ERR_FLASH_WRITE : BL_SUCCESS, blc.par1);
        break;
    }

    /* ---- STREAM_BEGIN: par1=page_num ---------------------------------- */
    case CAN_BL_CMD_STREAM_BEGIN:
        s_flash_in_progress = 1;
        if (blc.par1 < PAGE_COUNT)
        {
            stream_active = 1U;
            stream_page = blc.par1;
            memset(pagebuf, 0xFF, sizeof(pagebuf));
            memset(stream_rx_mask, 0, sizeof(stream_rx_mask));
            bl_can_tx_resp(CAN_BL_CMD_STREAM_BEGIN, BL_SUCCESS, blc.par1);
        }
        else
        {
            bl_can_tx_resp(CAN_BL_CMD_STREAM_BEGIN, BL_ERR_INVALID_PAGE_NUM, blc.par1);
        }
        break;

    /* ---- STREAM_STATUS: par1=last 8-byte frame index to check ---------- */
    case CAN_BL_CMD_STREAM_STATUS:
        s_flash_in_progress = 1;
        if (!stream_active)
        {
            bl_can_tx_resp(CAN_BL_CMD_STREAM_STATUS, BL_ERR_INVALID_PAGE_NUM, blc.par1);
        }
        else if ((blc.par1 >= CAN_STREAM_FRAME_COUNT) || (stream_page >= PAGE_COUNT))
        {
            bl_can_tx_resp(CAN_BL_CMD_STREAM_STATUS, BL_ERR_INVALID_OFFSET, blc.par1);
        }
        else
        {
            uint8_t ok = stream_range_complete(stream_rx_mask, (uint8_t)blc.par1);
            bl_can_tx_resp(CAN_BL_CMD_STREAM_STATUS, ok ? BL_SUCCESS : BL_ERR_INVALID_CRC, blc.par1);
        }
        break;

    /* ---- SET_ID: par1=new_board_id ------------------------------------- */
    case CAN_BL_CMD_SET_ID:
        if (blc.par1 <= BL_BOARD_ID_MAX)
        {
            struct bl_vars_t vars  = *FLASH_VARS;
            vars.board.id          = (uint8_t)blc.par1;
            uint8_t r = fls_wr(APP_BASE - PAGE_SIZE, (uint32_t *)&vars,
                               sizeof(vars) / 4);
            bl_can_tx_resp(CAN_BL_CMD_SET_ID, r ? BL_ERR_FLASH_WRITE : BL_SUCCESS, blc.par1);
        }
        else
        {
            bl_can_tx_resp(CAN_BL_CMD_SET_ID, BL_ERR_INVALID_PAGE_NUM, blc.par1);
        }
        break;

    default:
        break;
    }
}

/* --------------------------------------------------------------------------
 * can_bl_irq — called from USB_LP_CAN1_RX0_IRQHandler.
 * ---------------------------------------------------------------------- */
void can_bl_irq(CAN_HandleTypeDef *pcan)
{
    while (HAL_CAN_GetRxFifoFillLevel(pcan, CAN_RX_FIFO0) > 0U)
    {
        CAN_RxHeaderTypeDef msg;
        uint8_t data[8];
        if (HAL_CAN_GetRxMessage(pcan, CAN_RX_FIFO0, &msg, data) != HAL_OK)
            return;
        process_can_msg(&msg, data);
    }
}

uint8_t can_bl_message_received(void)
{
    return s_message_received;
}

uint32_t can_bl_last_rx_tick(void)
{
    return s_lastcanrx;
}

uint8_t can_bl_flash_in_progress(void)
{
    return s_flash_in_progress;
}

/* HAL callback registered via HAL_CAN_RegisterCallback */
void can_bl_irq_callback(CAN_HandleTypeDef *pcan)
{
    can_bl_irq(pcan);
}
