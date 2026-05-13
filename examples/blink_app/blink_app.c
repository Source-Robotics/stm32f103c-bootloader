/* blink_app.c - test app for validating the STM32F103C bootloader.
 * Linked at 0x08003000 (app slot, after 12 KB bootloader).
 * Pattern: smooth LED fade up/down.
 * Drives both PA7 (v170 batch) and PB13 (standard board). */

#define SCB_VTOR    (*(volatile unsigned *)0xE000ED08)
#define RCC_APB2ENR (*(volatile unsigned *)0x40021018)
#define GPIOA_CRL   (*(volatile unsigned *)0x40010800)
#define GPIOA_BSRR  (*(volatile unsigned *)0x40010810)
#define GPIOA_BRR   (*(volatile unsigned *)0x40010814)
#define GPIOB_CRH   (*(volatile unsigned *)0x40010C04)
#define GPIOB_BSRR  (*(volatile unsigned *)0x40010C10)
#define GPIOB_BRR   (*(volatile unsigned *)0x40010C14)

static void delay(volatile unsigned n) { while (n--); }

static void led_on(void)  { GPIOA_BRR  = (1u << 7);  GPIOB_BRR  = (1u << 13); }
static void led_off(void) { GPIOA_BSRR = (1u << 7);  GPIOB_BSRR = (1u << 13); }

#define PWM_TOP       96U
#define PWM_TICK      220U
#define FADE_HOLD     22U
#define END_PAUSE     90000U

static void pwm_step(unsigned duty)
{
    for (unsigned i = 0; i < FADE_HOLD; i++)
    {
        if (duty > 0U)
        {
            led_on();
            delay(duty * PWM_TICK);
        }

        if (duty < PWM_TOP)
        {
            led_off();
            delay((PWM_TOP - duty) * PWM_TICK);
        }
    }
}

static void fade_up(void)
{
    for (unsigned duty = 0; duty <= PWM_TOP; duty++)
        pwm_step(duty);
}

static void fade_down(void)
{
    for (unsigned duty = PWM_TOP; duty > 0U; duty--)
        pwm_step(duty - 1U);
}

int main(void)
{
    /* Relocate vector table to app base. */
    SCB_VTOR = 0x08003000;

    /* Enable GPIOA + GPIOB clocks. */
    RCC_APB2ENR |= (1u << 2) | (1u << 3);

    /* PA7: output push-pull 2 MHz, CRL bits [31:28]. */
    GPIOA_CRL = (GPIOA_CRL & ~(0xFu << 28)) | (0x2u << 28);
    /* PB13: output push-pull 2 MHz, CRH bits [23:20]. */
    GPIOB_CRH = (GPIOB_CRH & ~(0xFu << 20)) | (0x2u << 20);
    led_off();

    while (1)
    {
        fade_up();
        delay(END_PAUSE);
        fade_down();
        delay(END_PAUSE);
    }
}
