"""
generate_icon.py — Generates a multi-resolution Windows .ico file for PaperTrade.io.
"""

import os
from PIL import Image, ImageDraw

def create_trading_icon():
    resources_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(resources_dir, exist_ok=True)
    ico_path = os.path.join(resources_dir, "app_icon.ico")
    png_path = os.path.join(resources_dir, "app_icon.png")

    sizes = [16, 32, 48, 64, 128, 256]
    images = []

    for size in sizes:
        # Create image with transparent background
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Scale factor
        s = size / 256.0

        # Draw rounded dark slate badge
        pad = int(8 * s)
        corner_r = int(50 * s)
        draw.rounded_rectangle(
            [pad, pad, size - pad, size - pad],
            radius=corner_r,
            fill=(14, 17, 23, 255),
            outline=(41, 98, 255, 230),
            width=max(1, int(6 * s))
        )

        # Draw grid lines (subtle)
        grid_col = (30, 36, 48, 160)
        draw.line([30 * s, 160 * s, 226 * s, 160 * s], fill=grid_col, width=max(1, int(2 * s)))
        draw.line([30 * s, 100 * s, 226 * s, 100 * s], fill=grid_col, width=max(1, int(2 * s)))

        # Candlestick 1 (red, bearish)
        # wick
        draw.line([75 * s, 110 * s, 75 * s, 180 * s], fill=(255, 82, 82, 255), width=max(1, int(3 * s)))
        # body
        draw.rectangle([65 * s, 130 * s, 85 * s, 165 * s], fill=(255, 82, 82, 255))

        # Candlestick 2 (green, bullish)
        # wick
        draw.line([135 * s, 70 * s, 135 * s, 160 * s], fill=(0, 230, 118, 255), width=max(1, int(3 * s)))
        # body
        draw.rectangle([125 * s, 90 * s, 145 * s, 140 * s], fill=(0, 230, 118, 255))

        # Candlestick 3 (cyan/blue, breakout)
        # wick
        draw.line([195 * s, 40 * s, 195 * s, 125 * s], fill=(0, 229, 255, 255), width=max(1, int(3 * s)))
        # body
        draw.rectangle([185 * s, 55 * s, 205 * s, 105 * s], fill=(0, 229, 255, 255))

        # Pulse trend line across the chart
        trend_points = [
            (35 * s, 170 * s),
            (75 * s, 148 * s),
            (110 * s, 155 * s),
            (135 * s, 115 * s),
            (170 * s, 90 * s),
            (195 * s, 75 * s),
            (225 * s, 50 * s)
        ]
        draw.line(trend_points, fill=(41, 98, 255, 255), width=max(2, int(7 * s)), joint="curve")
        draw.line(trend_points, fill=(255, 255, 255, 240), width=max(1, int(3 * s)), joint="curve")

        images.append(img)

    # Save highest res PNG
    images[-1].save(png_path, format="PNG")

    # Save multi-size ICO
    images[0].save(
        ico_path,
        format="ICO",
        sizes=[(img.width, img.height) for img in images],
        append_images=images[1:]
    )
    print(f"Generated {ico_path} and {png_path} successfully.")

if __name__ == "__main__":
    create_trading_icon()
