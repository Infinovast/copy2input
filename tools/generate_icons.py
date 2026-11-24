"""Generate Copy2Input's original artwork; Pillow is only needed at build time."""

from pathlib import Path

from PIL import Image, ImageDraw


ASSETS = Path(__file__).resolve().parents[1] / 'assets'
SCALE = 4
LIGHT_COLORS = {'ready': '#22c55e', 'typing': '#ef4444', 'paused': '#facc15'}


def draw_icon(state='idle', size=256, tray=False):
    image = Image.new('RGBA', (64 * SCALE, 64 * SCALE))
    draw = ImageDraw.Draw(image)

    def rounded(box, radius, fill, outline=None, width=1):
        draw.rounded_rectangle(tuple(round(value * SCALE) for value in box),
                               radius=radius * SCALE, fill=fill, outline=outline,
                               width=round(width * SCALE))

    def line(points, fill, width):
        draw.line([(round(x * SCALE), round(y * SCALE)) for x, y in points],
                  fill=fill, width=round(width * SCALE))

    rounded((0, 0, 63.75, 63.75) if tray else (1, 1, 63, 63),
            10 if tray else 13, '#0f6cbd')
    rounded((12, 13, 44, 56), 4, None, '#ffffff', 4 if tray else 3)
    rounded((20, 7, 36, 17), 2, '#ffffff')
    for y, end in ((26, 36), (35, 32), (44, 28)):
        rounded((20, y, end, y + (4 if tray else 2.5)), 1, '#ffffff')
    # A clear input caret, separated from the clipboard outline.
    rounded((37, 31, 57, 59), 2, '#0f6cbd')
    stroke = 4 if tray else 3
    line(((41, 34), (53, 34)), '#ffffff', stroke)
    line(((47, 34), (47, 56)), '#ffffff', stroke)
    line(((41, 56), (53, 56)), '#ffffff', stroke)

    if tray:
        tile = image.resize((54 * SCALE, 54 * SCALE), Image.Resampling.LANCZOS)
        image = Image.new('RGBA', image.size)
        image.paste(tile, (0, 10 * SCALE))
        if state in LIGHT_COLORS:
            ImageDraw.Draw(image).ellipse((34 * SCALE, 0, 64 * SCALE - 1, 30 * SCALE - 1),
                                          fill=LIGHT_COLORS[state], outline='#ffffff', width=2 * SCALE)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main():
    ASSETS.mkdir(exist_ok=True)
    base = draw_icon()
    base.save(ASSETS / 'Copy2Input.png')
    base.save(ASSETS / 'Copy2Input.ico', sizes=[(size, size) for size in
              (16, 20, 24, 32, 40, 48, 64, 128, 256)])
    for state in ('idle', *LIGHT_COLORS):
        draw_icon(state, 64, tray=True).save(ASSETS / f'tray-{state}.png')


if __name__ == '__main__':
    main()
