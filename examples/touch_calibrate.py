"""XPT2046 Touch Screen Calibration for NM-CYD-C5.

This script performs a 4-point calibration by prompting the user to touch
each corner of the screen. After calibration, it enters a drawing
verification mode where you can touch/drag anywhere to draw dots, making
it easy to visually confirm the calibration accuracy.
"""

import time
import st7789py as st7789
import tft_config
import vga1_16x16 as font
from xpt2046 import Touch
from machine import Pin

# SPI baudrate settings
# XPT2046 datasheet max is 2.5MHz; display uses 20MHz
TOUCH_BAUDRATE = 2500000
DISPLAY_BAUDRATE = 20000000

# UI layout
CLEAR_ZONE_HEIGHT = 30
BRUSH_SIZE = 3
BRUSH_COLOR = st7789.RED


def get_stable_raw_touch(spi, touch, samples=15):
    """Wait for touch, collect multiple samples, and return averaged raw values.

    Args:
        spi: SPI bus instance.
        touch: Touch controller instance.
        samples: Number of samples to collect and average.

    Returns:
        tuple: (avg_x, avg_y, avg_z) or None if no valid touch detected.
    """
    # Wait for finger press
    while True:
        spi.init(baudrate=TOUCH_BAUDRATE)
        z1 = touch.send_command(touch.GET_Z1)
        if z1 > 50:
            break
        spi.init(baudrate=DISPLAY_BAUDRATE)
        time.sleep_ms(50)

    # Collect samples while keeping low baudrate
    xs, ys, zs = [], [], []
    for _ in range(samples):
        x = touch.send_command(touch.GET_X)
        y = touch.send_command(touch.GET_Y)
        z1 = touch.send_command(touch.GET_Z1)

        if z1 > 50:
            xs.append(x)
            ys.append(y)
            zs.append(z1)
        time.sleep_ms(20)

    # Wait for finger release
    while True:
        z1 = touch.send_command(touch.GET_Z1)
        if z1 < 50:
            break
        time.sleep_ms(50)

    # Restore display baudrate
    spi.init(baudrate=DISPLAY_BAUDRATE)

    if len(xs) < 5:
        return None

    # Remove outliers and average the remaining values
    xs.sort()
    ys.sort()
    zs.sort()
    trim = max(1, len(xs) // 5)  # Trim ~20% from each end
    xs = xs[trim:-trim]
    ys = ys[trim:-trim]
    zs = zs[trim:-trim]

    return (
        sum(xs) // len(xs),
        sum(ys) // len(ys),
        sum(zs) // len(zs),
    )


def draw_target(tft, x, y, color=st7789.RED):
    """Draw a visible target marker at (x, y)."""
    size = 12
    tft.hline(x - size, y, size * 2 + 1, color)
    tft.vline(x, y - size, size * 2 + 1, color)
    tft.rect(x - 4, y - 4, 9, 9, color)


def calibrate_point(tft, spi, touch, label, x, y, point_num, total):
    """Show target at (x, y), wait for stable touch, return raw values."""
    tft.fill(st7789.BLACK)

    # Draw target marker at the corner
    draw_target(tft, x, y, st7789.RED)

    # Show instructions in the center area
    title = f"Point {point_num}/{total}"
    text = f"Touch: {label}"

    title_x = (tft.width - len(title) * font.WIDTH) // 2
    text_x = (tft.width - len(text) * font.WIDTH) // 2

    tft.text(font, title, title_x, 30, st7789.YELLOW, st7789.BLACK)
    tft.text(font, text, text_x, 50, st7789.WHITE, st7789.BLACK)

    # Wait for stable touch
    result = get_stable_raw_touch(spi, touch)

    if result:
        raw_x, raw_y, raw_z = result
        # Show immediate feedback
        feedback = f"OK: X={raw_x} Y={raw_y}"
        fb_x = (tft.width - len(feedback) * font.WIDTH) // 2
        tft.text(font, feedback, fb_x, 80, st7789.GREEN, st7789.BLACK)
        time.sleep_ms(800)
        return result

    return None


def show_results(tft, x_min, x_max, y_min, y_max, z_threshold):
    """Display calibration results on screen and print to console."""
    tft.fill(st7789.BLACK)

    lines = [
        "Calibration Done!",
        "",
        f"x_min={x_min}",
        f"x_max={x_max}",
        f"y_min={y_min}",
        f"y_max={y_max}",
        f"z_threshold={z_threshold}",
        "",
        "Touch to draw.",
        "Starting in 2s...",
    ]

    start_y = 10
    for i, line in enumerate(lines):
        color = st7789.GREEN if i == 0 else st7789.WHITE
        tft.text(font, line, 10, start_y + i * (font.HEIGHT + 4), color, st7789.BLACK)

    # Also print to serial console
    print("\n" + "=" * 44)
    print("      XPT2046 Calibration Results")
    print("=" * 44)
    print(f"  x_min       = {x_min}")
    print(f"  x_max       = {x_max}")
    print(f"  y_min       = {y_min}")
    print(f"  y_max       = {y_max}")
    print(f"  z_threshold = {z_threshold}")
    print("=" * 44)
    print("\nExample Touch() initializer:")
    print(f"    Touch(spi, cs=Pin(1), int_pin=None,")
    print(f"          x_min={x_min}, x_max={x_max},")
    print(f"          y_min={y_min}, y_max={y_max},")
    print(f"          z_threshold={z_threshold})")
    print("=" * 44 + "\n")

    time.sleep(2)


def draw_ui(tft):
    """Draw the verification mode UI."""
    tft.fill(st7789.BLACK)

    # Header info
    tft.text(font, "Touch to draw", 10, 5, st7789.GREEN, st7789.BLACK)
    tft.text(font, "Bottom = clear", 10, 25, st7789.YELLOW, st7789.BLACK)

    # Clear zone at bottom
    clear_y = tft.height - CLEAR_ZONE_HEIGHT
    tft.fill_rect(0, clear_y, tft.width, CLEAR_ZONE_HEIGHT, st7789.BLUE)
    clear_text = "CLEAR"
    text_x = (tft.width - len(clear_text) * font.WIDTH) // 2
    tft.text(font, clear_text, text_x, clear_y + 7, st7789.WHITE, st7789.BLUE)


def draw_brush(tft, x, y, color=BRUSH_COLOR, size=BRUSH_SIZE):
    """Draw a small square dot at (x, y) with boundary checking."""
    half = size // 2
    x0 = max(0, x - half)
    y0 = max(0, y - half)
    w = min(size, tft.width - x0)
    h = min(size, tft.height - y0)
    if w > 0 and h > 0:
        tft.fill_rect(x0, y0, w, h, color)


def update_coordinate_display(tft, x, y):
    """Update the coordinate display in the top-right corner."""
    coord = f"{x},{y}"
    # Clear the coordinate area
    tft.fill_rect(tft.width - 110, 5, 110, font.HEIGHT + 2, st7789.BLACK)
    # Draw new coordinate
    text_x = tft.width - len(coord) * font.WIDTH - 5
    tft.text(font, coord, text_x, 5, st7789.CYAN, st7789.BLACK)


def verify_mode(tft, spi, touch):
    """Interactive drawing verification mode.

    Touch anywhere to draw dots. Drag to draw lines.
    Touch the bottom blue area to clear the screen.
    """
    draw_ui(tft)
    clear_zone_y = tft.height - CLEAR_ZONE_HEIGHT

    print("Entering drawing verification mode...")
    print("Touch/drag to draw. Bottom area = clear. Ctrl-C to exit.\n")

    last_x, last_y = -1, -1

    while True:
        # Switch to touch baudrate
        spi.init(baudrate=TOUCH_BAUDRATE)

        # Quick check for touch using raw_touch (uses calibrated z_threshold)
        point = touch.raw_touch()

        if point is not None:
            # Normalize using calibration values
            norm_x, norm_y = touch.normalize(*point)

            # Transform to screen coordinates
            # Touch panel is 240x320 physical, screen is 320x240 (rotation=1)
            # So we swap X/Y to match
            screen_x = norm_y
            screen_y = norm_x

            # Clamp to screen bounds
            screen_x = max(0, min(screen_x, tft.width - 1))
            screen_y = max(0, min(screen_y, tft.height - 1))

            # Restore display baudrate before drawing
            spi.init(baudrate=DISPLAY_BAUDRATE)

            # Check if user touched the clear zone
            if screen_y >= clear_zone_y:
                draw_ui(tft)
                last_x, last_y = -1, -1
                # Debounce: wait for release
                while True:
                    spi.init(baudrate=TOUCH_BAUDRATE)
                    released = touch.raw_touch() is None
                    spi.init(baudrate=DISPLAY_BAUDRATE)
                    if released:
                        break
                    time.sleep_ms(50)
                continue

            # Draw dot at touch location
            draw_brush(tft, screen_x, screen_y)

            # Optionally draw a line segment if dragging (last position known)
            if last_x >= 0 and last_y >= 0:
                tft.line(last_x, last_y, screen_x, screen_y, BRUSH_COLOR)

            last_x, last_y = screen_x, screen_y

            # Update coordinate display
            update_coordinate_display(tft, screen_x, screen_y)

            # Small delay to control drawing rate
            time.sleep_ms(25)
        else:
            # No touch - restore baudrate and reset last position
            spi.init(baudrate=DISPLAY_BAUDRATE)
            last_x, last_y = -1, -1
            time.sleep_ms(30)


def main():
    """Run the 4-point touch calibration and verification."""
    print("Starting touch calibration...")
    print("Follow the on-screen prompts to touch each corner.\n")

    # Initialize display
    tft = tft_config.config(tft_config.WIDE)
    spi = tft_config.spi

    # Initialize touch with a wide, unfiltered range so calibration
    # values are not prematurely clipped.
    touch = Touch(
        spi,
        cs=Pin(1, Pin.OUT),
        int_pin=None,
        width=240,
        height=320,
        x_min=0,
        x_max=4095,
        y_min=0,
        y_max=4095,
        z_threshold=10,
    )

    # Use landscape orientation (rotation=1) to match typical usage
    tft.rotation(1)

    # Define 4 corner points with a small margin from the edges
    margin = 20
    corners = [
        ("TOP-LEFT", margin, margin),
        ("TOP-RIGHT", tft.width - 1 - margin, margin),
        ("BOTTOM-LEFT", margin, tft.height - 1 - margin),
        ("BOTTOM-RIGHT", tft.width - 1 - margin, tft.height - 1 - margin),
    ]

    results = []

    for i, (label, x, y) in enumerate(corners, 1):
        print(f"\n>>> Please touch: {label} (screen coords: {x}, {y})")
        result = calibrate_point(tft, spi, touch, label, x, y, i, len(corners))

        if result:
            raw_x, raw_y, raw_z = result
            results.append((label, raw_x, raw_y, raw_z))
            print(f"    Captured: raw_x={raw_x}, raw_y={raw_y}, z1={raw_z}")
        else:
            print("    ERROR: Failed to capture stable touch!")

    # Calculate calibration parameters from collected data
    if len(results) == 4:
        all_x = [r[1] for r in results]
        all_y = [r[2] for r in results]
        all_z = [r[3] for r in results]

        # Add a small margin to the calibrated range so edge touches
        # are still accepted during verification.
        MARGIN_ADC = 30
        x_min = max(0, min(all_x) - MARGIN_ADC)
        x_max = min(4095, max(all_x) + MARGIN_ADC)
        y_min = max(0, min(all_y) - MARGIN_ADC)
        y_max = min(4095, max(all_y) + MARGIN_ADC)

        # Set z_threshold well below the lightest touch observed
        z_threshold = max(30, min(all_z) - 100)

        # Update touch object with calibrated values
        touch.x_min = x_min
        touch.x_max = x_max
        touch.y_min = y_min
        touch.y_max = y_max
        touch.z_threshold = z_threshold
        # Recalculate normalization multipliers
        touch.x_multiplier = touch.width / (x_max - x_min)
        touch.x_add = x_min * -touch.x_multiplier
        touch.y_multiplier = touch.height / (y_max - y_min)
        touch.y_add = y_min * -touch.y_multiplier

        # Show results on screen
        show_results(tft, x_min, x_max, y_min, y_max, z_threshold)

        # Enter interactive drawing verification mode
        try:
            verify_mode(tft, spi, touch)
        except KeyboardInterrupt:
            print("\nVerification mode exited.")

    else:
        error_msg = "Calibration failed!"
        tft.fill(st7789.BLACK)
        tft.text(font, error_msg, 10, tft.height // 2, st7789.RED, st7789.BLACK)
        print(f"\n{error_msg}")
        print("Please try again.\n")


if __name__ == "__main__":
    main()
