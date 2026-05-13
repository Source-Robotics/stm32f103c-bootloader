/* STM32F103C CAN/UART Bootloader - main.c
 * Target: STM32F103CBT6 (128 KB flash, 20 KB SRAM)
 */

#include "main.h"
#include "bootloader.h"
#include "can_bl.h"
#include "uart_bl.h"
#include "flash_if.h"
#include "version.h"

/* HAL peripheral handles --------------------------------------------------- */
CAN_HandleTypeDef  hcan;
CRC_HandleTypeDef  hcrc;
IWDG_HandleTypeDef hiwdg;
UART_HandleTypeDef huart1;

/* Private function prototypes --------------------------------------------- */
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_CAN_Init(void);
static void MX_USART1_UART_Init(void);
static void MX_CRC_Init(void);
static void MX_IWDG_Init(void);
static void EarlyStatusBlink(void);
static void InitFlashConfigIfNeeded(void);
static uint8_t BootableAppIsValid(void);
static uint8_t BootActivitySeen(void);
static uint32_t LastBootActivityTick(void);
static void UpdateStatusLed(uint8_t activity_seen);

/* --------------------------------------------------------------------------
 * main()
 *
 * Boot sequence:
 *  1. PreSystemInit() runs first from startup assembly. If the SRAM magic is
 *     set by the bootloader reset path, it jumps directly to the app.
 *  2. HAL_Init() + SystemClock_Config() bring up the MCU at 72 MHz.
 *  3. The flash config page is refreshed when a new bootloader build is seen.
 *  4. CAN, UART, CRC, GPIO, and IWDG are initialized.
 *  5. The main loop listens for bootloader packets, feeds IWDG, and resets to
 *     the app when the timeout expires and the stored app CRC is valid. If the
 *     app is invalid or partially written, it stays in bootloader mode.
 * ---------------------------------------------------------------------- */
int main(void)
{
    EarlyStatusBlink();

    HAL_Init();
    SystemClock_Config();

    MX_GPIO_Init();
    MX_CAN_Init();
    MX_USART1_UART_Init();
    MX_CRC_Init();
    MX_IWDG_Init();

    InitFlashConfigIfNeeded();

    uint32_t next_app_check_tick = 0U;

    while (1)
    {
        uint32_t now = HAL_GetTick();
        uint8_t activity_seen = BootActivitySeen();
        UpdateStatusLed(activity_seen);

        uint8_t flashing = can_bl_flash_in_progress() || uart_bl_flash_in_progress();
        uint32_t timeout = flashing ? FLASH_INPROGRESS_TO
                                    : (activity_seen ? NOCANRX_TO : STARTUP_TO);
        if ((now - LastBootActivityTick() > timeout) &&
            ((int32_t)(now - next_app_check_tick) >= 0))
        {
            if (BootableAppIsValid())
            {
                *(MAGIC_ADDR) = MAGIC_VAL;
                __NVIC_SystemReset();
            }
            next_app_check_tick = now + 1000U;
        }

        HAL_IWDG_Refresh(&hiwdg);
    }
}

static void EarlyStatusBlink(void)
{
    /* Register-only LED probe before HAL and clocks are initialized. */
    RCC->APB2ENR |= (1u << 2) | (1u << 3);
    GPIOA->CRL = (GPIOA->CRL & ~(0xFu << 28)) | (0x2u << 28);
    GPIOB->CRH = (GPIOB->CRH & ~(0xFu << 20)) | (0x2u << 20);

    for (int flash = 0; flash < 3; flash++)
    {
        GPIOA->BSRR = GPIO_PIN_7;
        GPIOB->BSRR = GPIO_PIN_13;
        for (volatile uint32_t delay = 0; delay < 1000000UL; delay++);

        GPIOA->BRR = GPIO_PIN_7;
        GPIOB->BRR = GPIO_PIN_13;
        for (volatile uint32_t delay = 0; delay < 1000000UL; delay++);
    }
}

static void InitFlashConfigIfNeeded(void)
{
    if (UNIX_TIMESTAMP == FLASH_VARS->board.bl_build_version)
        return;

    struct bl_vars_t new_bl_vars = {0};
    new_bl_vars.board.id = bl_board_id();
    new_bl_vars.board.bl_build_version = UNIX_TIMESTAMP;

    if (fls_wr(APP_BASE - PAGE_SIZE, (uint32_t *)&new_bl_vars,
               sizeof(new_bl_vars) / 4) != 0U)
    {
        Error_Handler();
    }
}

static uint8_t BootableAppIsValid(void)
{
    if ((FLASH_VARS->app.page_count == 0U) ||
        (FLASH_VARS->app.page_count > PAGE_COUNT))
    {
        return 0U;
    }

    uint32_t crc = HAL_CRC_Calculate(&hcrc, (uint32_t *)APP_BASE,
                                     FLASH_VARS->app.page_count * PAGE_SIZE);
    return (crc == FLASH_VARS->app.crc) ? 1U : 0U;
}

static uint8_t BootActivitySeen(void)
{
    return (can_bl_message_received() || uart_bl_message_received()) ? 1U : 0U;
}

static uint32_t LastBootActivityTick(void)
{
    uint32_t last_tick = can_bl_last_rx_tick();
    uint32_t uart_tick = uart_bl_last_rx_tick();
    return (uart_tick > last_tick) ? uart_tick : last_tick;
}

static void UpdateStatusLed(uint8_t activity_seen)
{
    if (activity_seen)
    {
        uint32_t t = HAL_GetTick() % 200U;
        if (t < 100U) { LED_ON(); } else { LED_OFF(); }
        return;
    }

    uint32_t t = HAL_GetTick() % 1000U;
    if      (t < 80U)  { LED_ON();  }
    else if (t < 180U) { LED_OFF(); }
    else if (t < 260U) { LED_ON();  }
    else               { LED_OFF(); }
}

/* --------------------------------------------------------------------------
 * SystemClock_Config - 72 MHz from HSE 8 MHz via PLL x9
 * APB1 = 36 MHz (CAN), APB2 = 72 MHz (USART1)
 * ---------------------------------------------------------------------- */
void SystemClock_Config(void)
{
    RCC_OscInitTypeDef RCC_OscInitStruct = {0};
    RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

    /* Configure HSE + PLL only. LSI is enabled automatically by IWDG. */
    RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
    RCC_OscInitStruct.HSEState       = RCC_HSE_ON;
    RCC_OscInitStruct.HSEPredivValue = RCC_HSE_PREDIV_DIV1;
    RCC_OscInitStruct.PLL.PLLState   = RCC_PLL_ON;
    RCC_OscInitStruct.PLL.PLLSource  = RCC_PLLSOURCE_HSE;
    RCC_OscInitStruct.PLL.PLLMUL     = RCC_PLL_MUL9;  /* 8 MHz x 9 = 72 MHz */
    if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
        Error_Handler();

    RCC_ClkInitStruct.ClockType      = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK
                                     | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
    RCC_ClkInitStruct.SYSCLKSource   = RCC_SYSCLKSOURCE_PLLCLK;
    RCC_ClkInitStruct.AHBCLKDivider  = RCC_SYSCLK_DIV1;   /* AHB  = 72 MHz */
    RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV2;     /* APB1 = 36 MHz */
    RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;     /* APB2 = 72 MHz */
    if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_2) != HAL_OK)
        Error_Handler();
}

/* --------------------------------------------------------------------------
 * MX_GPIO_Init - enable AFIO and configure both supported LED pins.
 * CAN and USART1 remaps are handled in their MSP init functions.
 * ---------------------------------------------------------------------- */
static void MX_GPIO_Init(void)
{
    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_AFIO_CLK_ENABLE();

    GPIO_InitTypeDef GPIO_InitStruct = {0};
    GPIO_InitStruct.Mode  = GPIO_MODE_OUTPUT_PP;
    GPIO_InitStruct.Pull  = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;

    GPIO_InitStruct.Pin = GPIO_PIN_7;
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

    GPIO_InitStruct.Pin = GPIO_PIN_13;
    HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

    LED_OFF();
}

/* --------------------------------------------------------------------------
 * MX_CAN_Init - CAN1 at 1 Mbit/s on PB8/PB9 (remap=2).
 * Matches the host application CAN bitrate.
 * ---------------------------------------------------------------------- */
static void MX_CAN_Init(void)
{
    hcan.Instance               = CAN1;
    hcan.Init.Prescaler         = 4;            /* 36 MHz / (4 x (1+6+2)) = 1 Mbit */
    hcan.Init.Mode              = CAN_MODE_NORMAL;
    hcan.Init.SyncJumpWidth     = CAN_SJW_1TQ;
    hcan.Init.TimeSeg1          = CAN_BS1_6TQ;
    hcan.Init.TimeSeg2          = CAN_BS2_2TQ;
    hcan.Init.TimeTriggeredMode = DISABLE;
    hcan.Init.AutoBusOff        = ENABLE;
    hcan.Init.AutoWakeUp        = DISABLE;
    hcan.Init.AutoRetransmission  = ENABLE;
    hcan.Init.ReceiveFifoLocked   = DISABLE;
    hcan.Init.TransmitFifoPriority = DISABLE;
    if (HAL_CAN_Init(&hcan) != HAL_OK)
        Error_Handler();

    CAN_FilterTypeDef sf = {0};
    sf.FilterMaskIdHigh     = 0x0000;
    sf.FilterMaskIdLow      = 0x0000;
    sf.FilterFIFOAssignment = CAN_FILTER_FIFO0;
    sf.FilterBank           = 0;
    sf.FilterMode           = CAN_FILTERMODE_IDMASK;
    sf.FilterScale          = CAN_FILTERSCALE_32BIT;
    sf.FilterActivation     = CAN_FILTER_ENABLE;
    if (HAL_CAN_ConfigFilter(&hcan, &sf) != HAL_OK)
        Error_Handler();

    if (HAL_CAN_RegisterCallback(&hcan, HAL_CAN_RX_FIFO0_MSG_PENDING_CB_ID, can_bl_irq_callback) != HAL_OK)
        Error_Handler();

    if (HAL_CAN_Start(&hcan) != HAL_OK)
        Error_Handler();

    if (HAL_CAN_ActivateNotification(&hcan, CAN_IT_RX_FIFO0_MSG_PENDING) != HAL_OK)
        Error_Handler();
}

/* --------------------------------------------------------------------------
 * MX_USART1_UART_Init - USART1 at 256000 bps 8N1 on PB6/PB7 (remap).
 * ---------------------------------------------------------------------- */
static void MX_USART1_UART_Init(void)
{
    huart1.Instance          = USART1;
    huart1.Init.BaudRate     = 256000;
    huart1.Init.WordLength   = UART_WORDLENGTH_8B;
    huart1.Init.StopBits     = UART_STOPBITS_1;
    huart1.Init.Parity       = UART_PARITY_NONE;
    huart1.Init.Mode         = UART_MODE_TX_RX;
    huart1.Init.HwFlowCtl    = UART_HWCONTROL_NONE;
    huart1.Init.OverSampling = UART_OVERSAMPLING_16;
    if (HAL_UART_Init(&huart1) != HAL_OK)
        Error_Handler();

    __HAL_UART_ENABLE_IT(&huart1, UART_IT_RXNE);
}

/* --------------------------------------------------------------------------
 * MX_CRC_Init - hardware CRC unit (poly 0x04C11DB7, init 0xFFFFFFFF).
 * ---------------------------------------------------------------------- */
static void MX_CRC_Init(void)
{
    hcrc.Instance = CRC;
    if (HAL_CRC_Init(&hcrc) != HAL_OK)
        Error_Handler();
}

/* --------------------------------------------------------------------------
 * MX_IWDG_Init - IWDG roughly 4 s (LSI ~40 kHz, /256, reload 625).
 * ---------------------------------------------------------------------- */
static void MX_IWDG_Init(void)
{
    hiwdg.Instance       = IWDG;
    hiwdg.Init.Prescaler = IWDG_PRESCALER_256;
    hiwdg.Init.Reload    = 625;
    if (HAL_IWDG_Init(&hiwdg) != HAL_OK)
        Error_Handler();
}

void Error_Handler(void)
{
    __disable_irq();
    RCC->APB2ENR |= (1u << 2) | (1u << 3);
    GPIOA->CRL = (GPIOA->CRL & ~(0xFu << 28)) | (0x2u << 28);
    GPIOB->CRH = (GPIOB->CRH & ~(0xFu << 20)) | (0x2u << 20);

    while (1)
    {
        for (int i = 0; i < 5; i++)
        {
            GPIOA->BRR  = GPIO_PIN_7;
            GPIOB->BRR  = GPIO_PIN_13;
            for (volatile uint32_t d = 0; d < 2000000UL; d++);

            GPIOA->BSRR = GPIO_PIN_7;
            GPIOB->BSRR = GPIO_PIN_13;
            for (volatile uint32_t d = 0; d < 2000000UL; d++);
        }
        for (volatile uint32_t d = 0; d < 8000000UL; d++);
    }
}
