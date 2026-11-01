"""
st7789.py - ST7789V2 Display Driver for Raspberry Pi 5
Target display: AE-ATM0130B3 (1.3" IPS LCD 240x240)

Features:
  - Hardware SPI0 communication (CS0 = GPIO8)
  - High-speed direct GPIO control for D/C (GPIO25) and /RES (GPIO24) via gpiod
  - Hardware PWM for Backlight duty cycle (GPIO23) via lgpio
  - Automatic 80px offset calculation for 240x240 panel in all rotations
  - Fast RGB888 to RGB565 vector conversion via NumPy
"""

import os
import sys
import time
import signal
import subprocess
import spidev
import gpiod
import lgpio
import numpy as np
from PIL import Image

BL_PID_FILE = "/tmp/atm0130_bl.pid"


def stop_backlight_daemon():
    """Stop external or previous backlight daemon if running."""
    if os.path.exists(BL_PID_FILE):
        try:
            with open(BL_PID_FILE, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.05)
        except Exception:
            pass
        try:
            os.remove(BL_PID_FILE)
        except Exception:
            pass


def start_backlight_daemon(pin: int, duty: float, freq: int = 1000):
    """Start detached daemon process to maintain PWM backlight on Raspberry Pi 5."""
    stop_backlight_daemon()
    duty = max(0.0, min(100.0, float(duty)))
    if duty >= 100.0:
        subprocess.run(["pinctrl", "set", str(pin), "op", "dh"], check=False)
        return
    elif duty <= 0.0:
        subprocess.run(["pinctrl", "set", str(pin), "op", "dl"], check=False)
        return

    pid = os.fork()
    if pid > 0:
        try:
            with open(BL_PID_FILE, "w") as f:
                f.write(str(pid))
        except Exception:
            pass
        return

    # Child process becomes daemon
    try:
        os.setsid()
        devnull = open(os.devnull, "wb+")
        os.dup2(devnull.fileno(), sys.stdin.fileno())
        os.dup2(devnull.fileno(), sys.stdout.fileno())
        os.dup2(devnull.fileno(), sys.stderr.fileno())

        h = lgpio.gpiochip_open(15)
        lgpio.gpio_claim_output(h, pin, 0)
        lgpio.tx_pwm(h, pin, freq, duty)
        while True:
            time.sleep(10)
    except Exception:
        sys.exit(1)

# ST7789 Commands
ST7789_NOP = 0x00
ST7789_SWRESET = 0x01
ST7789_SLPIN = 0x10
ST7789_SLPOUT = 0x11
ST7789_NORON = 0x13
ST7789_INVOFF = 0x20
ST7789_INVON = 0x21
ST7789_DISPOFF = 0x28
ST7789_DISPON = 0x29
ST7789_CASET = 0x2A
ST7789_RASET = 0x2B
ST7789_RAMWR = 0x2C
ST7789_MADCTL = 0x36
ST7789_COLMOD = 0x3A

# MADCTL orientation flags
MADCTL_MY = 0x80  # Page address order (top to bottom vs bottom to top)
MADCTL_MX = 0x40  # Column address order (left to right vs right to left)
MADCTL_MV = 0x20  # Page/Column order (reverse mode / row-column exchange)
MADCTL_ML = 0x10  # Line address order
MADCTL_BGR = 0x08 # Color selector switch control (0=RGB, 1=BGR)
MADCTL_MH = 0x04  # Display data latch order


class ST7789:
    """ST7789 display controller class for Raspberry Pi 5."""

    def __init__(
        self,
        width: int = 240,
        height: int = 240,
        rotation: int = 2,            # Default to 2 (180 deg, upright for AE-ATM0130B3)
        spi_port: int = 0,
        spi_cs: int = 0,
        spi_speed_hz: int = 24_000_000,
        gpio_chip: str = "gpiochip15",
        pin_dc: int = 25,             # BCM GPIO25 (Physical Pin 22)
        pin_res: int = 24,            # BCM GPIO24 (Physical Pin 18)
        pin_bl: int = 23,             # BCM GPIO23 (Physical Pin 16) - Backlight PWM
        bl_freq: int = 1000,          # PWM frequency (1000 Hz)
        bl_duty: float = 100.0,       # Initial brightness (0.0 to 100.0 %)
        x_offset: int = None,         # Auto-calculated if None
        y_offset: int = None,         # Auto-calculated if None
        invert_colors: bool = True,   # IPS displays typically require INVON
    ):
        self.width = width
        self.height = height
        self.rotation = rotation
        self.pin_dc = pin_dc
        self.pin_res = pin_res
        self.pin_bl = pin_bl
        self.bl_freq = bl_freq
        self.bl_duty = bl_duty
        self.custom_x_offset = x_offset
        self.custom_y_offset = y_offset
        self.x_offset = 0
        self.y_offset = 0
        self.invert_colors = invert_colors

        # 1. Initialize D/C and /RES pins via proven gpiod
        self.chip = gpiod.Chip(gpio_chip)
        self.line_dc = self.chip.get_line(pin_dc)
        self.line_res = self.chip.get_line(pin_res)

        self.line_dc.request(consumer="st7789_dc", type=gpiod.LINE_REQ_DIR_OUT)
        self.line_res.request(consumer="st7789_res", type=gpiod.LINE_REQ_DIR_OUT)

        # 2. Initialize Backlight via lgpio PWM
        self.h_lgpio = None
        if self.pin_bl is not None:
            stop_backlight_daemon()
            try:
                self.h_lgpio = lgpio.gpiochip_open(15)
                lgpio.gpio_claim_output(self.h_lgpio, self.pin_bl, 0)
                self.set_backlight(self.bl_duty)
            except Exception as e:
                print(f"[Warning] Failed to initialize backlight PWM: {e}")

        # 3. Initialize SPI
        self.spi = spidev.SpiDev()
        self.spi.open(spi_port, spi_cs)
        self.spi.max_speed_hz = spi_speed_hz
        self.spi.mode = 0  # Mode 0 (CPOL=0, CPHA=0)

        # 4. Hardware & Software Initialization
        self.init_display()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def set_backlight(self, duty: float):
        """Set backlight brightness using PWM duty cycle (0.0% to 100.0%)."""
        if self.pin_bl is None or self.h_lgpio is None:
            return
        duty = max(0.0, min(100.0, float(duty)))
        self.bl_duty = duty
        lgpio.tx_pwm(self.h_lgpio, self.pin_bl, self.bl_freq, duty)
        if duty >= 100.0:
            try:
                subprocess.run(["pinctrl", "set", str(self.pin_bl), "op", "dh"], check=False)
            except Exception:
                pass
        elif duty <= 0.0:
            try:
                subprocess.run(["pinctrl", "set", str(self.pin_bl), "op", "dl"], check=False)
            except Exception:
                pass

    def close(self):
        """Clean up SPI and GPIO resources while maintaining backlight."""
        if hasattr(self, "spi") and self.spi:
            self.spi.close()
            self.spi = None
        if hasattr(self, "line_dc") and self.line_dc:
            self.line_dc.release()
            self.line_dc = None
        if hasattr(self, "line_res") and self.line_res:
            self.line_res.release()
            self.line_res = None
        if hasattr(self, "chip") and self.chip:
            self.chip.close()
            self.chip = None
        if hasattr(self, "h_lgpio") and self.h_lgpio is not None:
            duty = self.bl_duty
            pin = self.pin_bl
            freq = self.bl_freq
            lgpio.gpiochip_close(self.h_lgpio)
            self.h_lgpio = None
            if duty >= 100.0:
                try:
                    subprocess.run(["pinctrl", "set", str(pin), "op", "dh"], check=False)
                except Exception:
                    pass
            elif duty <= 0.0:
                try:
                    subprocess.run(["pinctrl", "set", str(pin), "op", "dl"], check=False)
                except Exception:
                    pass
            else:
                start_backlight_daemon(pin, duty, freq)

    def _set_dc(self, high: bool):
        self.line_dc.set_value(1 if high else 0)

    def _set_res(self, high: bool):
        self.line_res.set_value(1 if high else 0)

    def reset(self):
        """Perform hardware reset via /RES pin."""
        self._set_res(True)
        time.sleep(0.02)
        self._set_res(False)
        time.sleep(0.05)
        self._set_res(True)
        time.sleep(0.15)

    def command(self, cmd: int, *data):
        """Send command byte, followed by optional data bytes."""
        self._set_dc(False)
        self.spi.writebytes([cmd])
        if data:
            self._set_dc(True)
            self.spi.writebytes(list(data))

    def data(self, data_bytes: bytes):
        """Send raw data stream over SPI in chunks of up to 4096 bytes."""
        self._set_dc(True)
        chunk_size = 4096
        total = len(data_bytes)
        for i in range(0, total, chunk_size):
            self.spi.writebytes(data_bytes[i : i + chunk_size])

    def set_rotation(self, rotation: int):
        """Configure rotation and automatic 80px offset calculation for 240x240 panel."""
        self.rotation = rotation % 4
        if self.rotation == 0:
            madctl = 0x00
            default_x, default_y = 0, 0
        elif self.rotation == 1:
            madctl = MADCTL_MX | MADCTL_MV
            default_x, default_y = 0, 0
        elif self.rotation == 2:
            madctl = MADCTL_MX | MADCTL_MY  # 180 degrees
            default_x, default_y = 0, 80    # Y offset 80px aligns 240x240 active area!
        elif self.rotation == 3:
            madctl = MADCTL_MY | MADCTL_MV
            default_x, default_y = 80, 0

        self.x_offset = self.custom_x_offset if self.custom_x_offset is not None else default_x
        self.y_offset = self.custom_y_offset if self.custom_y_offset is not None else default_y

        self.command(ST7789_MADCTL, madctl)

    def init_display(self):
        """Send ST7789 initialization sequence."""
        self.reset()

        self.command(ST7789_SWRESET)
        time.sleep(0.15)

        self.command(ST7789_SLPOUT)
        time.sleep(0.12)

        # 16-bit color (RGB565)
        self.command(ST7789_COLMOD, 0x55)
        time.sleep(0.01)

        # Memory data access control & offsets
        self.set_rotation(self.rotation)

        # Color inversion for IPS display
        if self.invert_colors:
            self.command(ST7789_INVON)
        else:
            self.command(ST7789_INVOFF)
        time.sleep(0.01)

        # Normal display mode on
        self.command(ST7789_NORON)
        time.sleep(0.01)

        # Display on
        self.command(ST7789_DISPON)
        time.sleep(0.12)

    def set_window(self, x0: int, y0: int, x1: int, y1: int):
        """Set drawing window coordinates with offsets."""
        xa0 = x0 + self.x_offset
        xa1 = x1 + self.x_offset
        ya0 = y0 + self.y_offset
        ya1 = y1 + self.y_offset

        self.command(ST7789_CASET, (xa0 >> 8) & 0xFF, xa0 & 0xFF, (xa1 >> 8) & 0xFF, xa1 & 0xFF)
        self.command(ST7789_RASET, (ya0 >> 8) & 0xFF, ya0 & 0xFF, (ya1 >> 8) & 0xFF, ya1 & 0xFF)
        self.command(ST7789_RAMWR)

    def display(self, image: Image.Image):
        """Render a PIL Image to the ST7789 display."""
        if image.size != (self.width, self.height):
            image = image.resize((self.width, self.height), Image.Resampling.BILINEAR)

        if image.mode != "RGB":
            image = image.convert("RGB")

        # Convert RGB888 image to RGB565 format using NumPy for high performance
        arr = np.asarray(image, dtype=np.uint16)
        r = (arr[..., 0] >> 3) & 0x1F
        g = (arr[..., 1] >> 2) & 0x3F
        b = (arr[..., 2] >> 3) & 0x1F
        rgb565 = (r << 11) | (g << 5) | b

        # Convert to Big Endian byte sequence for ST7789
        raw_bytes = rgb565.byteswap().tobytes()

        # Send full window data
        self.set_window(0, 0, self.width - 1, self.height - 1)
        self.data(raw_bytes)

    def clear(self, color=(0, 0, 0)):
        """Clear entire display with a solid color."""
        img = Image.new("RGB", (self.width, self.height), color)
        self.display(img)
