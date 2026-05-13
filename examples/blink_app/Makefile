CC      = arm-none-eabi-gcc
OBJCOPY = arm-none-eabi-objcopy
CFLAGS  = -mcpu=cortex-m3 -mthumb -Os -Wall -ffunction-sections -fdata-sections
LDFLAGS = -mcpu=cortex-m3 -mthumb -Tblink_app.ld -Wl,--gc-sections -nostartfiles

all: blink_app.bin

blink_app.elf: blink_app.c startup.s
	$(CC) $(CFLAGS) $(LDFLAGS) blink_app.c startup.s -o blink_app.elf
	arm-none-eabi-size blink_app.elf

blink_app.bin: blink_app.elf
	$(OBJCOPY) -O binary blink_app.elf blink_app.bin
	@echo "Done: blink_app.bin"

clean:
	del /Q blink_app.elf blink_app.bin 2>NUL || true
