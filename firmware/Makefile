##########################################################################################################################
# STM32F103C CAN/UART Bootloader — Makefile
# Target: STM32F103CBT6 (128 KB flash, 20 KB SRAM)
# Toolchain: arm-none-eabi-gcc
# Build: make -j4
# Flash: make flash  (requires OpenOCD + JTAG probe)
##########################################################################################################################

TARGET = stm32f103c_bl
DEBUG  = 0
OPT    = -Os

BUILD_DIR = build

######################################
# Source files
######################################
C_SOURCES = \
Core/Src/main.c \
Core/Src/bootloader.c \
Core/Src/can_bl.c \
Core/Src/uart_bl.c \
Core/Src/flash_if.c \
Core/Src/stm32f1xx_hal_msp.c \
Core/Src/stm32f1xx_it.c \
Core/Src/system_stm32f1xx.c \
Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal.c \
Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_rcc.c \
Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_rcc_ex.c \
Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_gpio.c \
Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_gpio_ex.c \
Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_dma.c \
Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_cortex.c \
Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_pwr.c \
Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_flash.c \
Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_flash_ex.c \
Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_exti.c \
Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_can.c \
Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_crc.c \
Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_iwdg.c \
Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_uart.c \
Drivers/STM32F1xx_HAL_Driver/Src/stm32f1xx_hal_usart.c

ASM_SOURCES = startup_stm32f103xb.s

######################################
# Toolchain
######################################
PREFIX     = arm-none-eabi-
CC         = $(PREFIX)gcc
AS         = $(PREFIX)gcc -x assembler-with-cpp
CP         = $(PREFIX)objcopy
SZ         = $(PREFIX)size
HEX        = $(CP) -O ihex
BIN        = $(CP) -O binary -S

######################################
# CFLAGS
######################################
CPU    = -mcpu=cortex-m3
MCU    = $(CPU) -mthumb

# Macros
C_DEFS = \
-DUSE_HAL_DRIVER \
-DSTM32F103xB

# Include paths
C_INCLUDES = \
-ICore/Inc \
-IDrivers/STM32F1xx_HAL_Driver/Inc \
-IDrivers/STM32F1xx_HAL_Driver/Inc/Legacy \
-IDrivers/CMSIS/Device/ST/STM32F1xx/Include \
-IDrivers/CMSIS/Include

ASFLAGS = $(MCU) $(AS_DEFS) $(AS_INCLUDES) $(OPT) -Wall -fdata-sections -ffunction-sections

CFLAGS += $(MCU) $(C_DEFS) $(C_INCLUDES) $(OPT) -Wall -fdata-sections -ffunction-sections -std=c11

ifeq ($(DEBUG), 1)
CFLAGS += -g -gdwarf-2
endif

CFLAGS += -MMD -MP -MF"$(@:%.o=%.d)"

######################################
# LDFLAGS
######################################
LDSCRIPT = STM32F103CBTx_FLASH.ld
LIBS     = -lc -lm -lnosys
LIBDIR   =
LDFLAGS  = $(MCU) -specs=nano.specs -T$(LDSCRIPT) $(LIBDIR) $(LIBS) \
           -Wl,-Map=$(BUILD_DIR)/$(TARGET).map,--cref -Wl,--gc-sections

######################################
# Build rules
######################################
all: $(BUILD_DIR)/$(TARGET).elf $(BUILD_DIR)/$(TARGET).hex $(BUILD_DIR)/$(TARGET).bin

OBJECTS  = $(addprefix $(BUILD_DIR)/,$(notdir $(C_SOURCES:.c=.o)))
vpath %.c $(sort $(dir $(C_SOURCES)))
OBJECTS += $(addprefix $(BUILD_DIR)/,$(notdir $(ASM_SOURCES:.s=.o)))
vpath %.s $(sort $(dir $(ASM_SOURCES)))

$(BUILD_DIR)/%.o: %.c Makefile | $(BUILD_DIR)
	$(CC) -c $(CFLAGS) -Wa,-a,-ad,-alms=$(BUILD_DIR)/$(notdir $(<:.c=.lst)) $< -o $@

$(BUILD_DIR)/%.o: %.s Makefile | $(BUILD_DIR)
	$(AS) -c $(ASFLAGS) $< -o $@

$(BUILD_DIR)/$(TARGET).elf: $(OBJECTS) Makefile
	$(CC) $(OBJECTS) $(LDFLAGS) -o $@
	$(SZ) $@

$(BUILD_DIR)/%.hex: $(BUILD_DIR)/%.elf | $(BUILD_DIR)
	$(HEX) $< $@

$(BUILD_DIR)/%.bin: $(BUILD_DIR)/%.elf | $(BUILD_DIR)
	$(BIN) $< $@

$(BUILD_DIR):
	mkdir -p $@

######################################
# Flash target (JTAG via OpenOCD)
######################################
flash: $(BUILD_DIR)/$(TARGET).elf
	openocd -f openocd.cfg -c "program $(BUILD_DIR)/$(TARGET).elf verify reset exit"

######################################
# Clean
######################################
clean:
	-rm -fR $(BUILD_DIR)

-include $(wildcard $(BUILD_DIR)/*.d)
