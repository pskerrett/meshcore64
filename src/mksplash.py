#!/usr/bin/env python3
"""
Build the v2.2 splash: MeshCore wordmark, "64" in the Commodore font, and
a drawing of a breadbin C64.

Supersedes mklogo.py, which only placed the wordmark. Hires is 320x200
with one bit per pixel and one foreground/background pair per 8x8 cell,
stored in cell order rather than as a linear framebuffer -- so the packer
has to walk cells, and colour is a separate 1000-byte map.

Rather than ship that map, a colour is chosen per screen row (25 bytes)
and the client expands it. The layout is horizontal bands anyway: teal
wordmark, light-blue "64", grey machine.

The "64" glyphs come from the real character ROM, so they are the actual
Commodore font rather than something that merely resembles it.
"""
import os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
LOGO = "/data/meshcore/logo/meshcore.png"
CHARGEN = "/usr/share/vice/C64/chargen-901225-01.bin"

W, H = 320, 200

# --- band layout, in pixels ---
LOGO_W = 256
LOGO_X = (W - LOGO_W) // 2
LOGO_Y = 8

DIG_SC = 5                      # 8x8 glyph scaled to 40x40
DIG_Y = 52
DIG_X = (W - 2 * 8 * DIG_SC) // 2

MACH_X0, MACH_X1 = 38, 282
MACH_TOP = 104                  # back edge of the top surface
MACH_FRONT = 122                # where the top meets the front face
MACH_BOT = 192

# colours by band: high nibble is the hires foreground
C_LOGO = 3                      # cyan, close to the MeshCore teal
C_DIG = 14                      # light blue, the C64's own
C_MACH = 15                     # light grey


def wordmark(page):
    im = Image.open(LOGO).convert("RGBA")
    alpha = im.split()[3]       # near-white line art on transparent
    alpha = alpha.crop(alpha.getbbox())
    # The source carries a superscript trademark mark after the final E.
    # There is a clean empty column between the two, so cutting at the
    # last column with ink below the cap line removes it exactly.
    px = alpha.load()
    w, h = alpha.size
    cut = w
    for x in range(w - 1, 0, -1):
        if any(px[x, y] >= 128 for y in range(h // 4, h)):
            cut = x + 1
            break
    alpha = alpha.crop((0, 0, cut, h))
    alpha = alpha.crop(alpha.getbbox())
    w, h = alpha.size
    nh = max(1, int(round(h * LOGO_W / float(w))))
    page.paste(alpha.resize((LOGO_W, nh), Image.LANCZOS), (LOGO_X, LOGO_Y))
    return nh


def digits(d):
    """'6' and '4' straight out of the character ROM, scaled up."""
    rom = open(CHARGEN, "rb").read()
    for i, ch in enumerate("64"):
        code = ord(ch)           # digits are screen codes 0x30-0x39
        glyph = rom[code * 8:code * 8 + 8]
        for row in range(8):
            bits = glyph[row]
            for bit in range(8):
                if bits & (0x80 >> bit):
                    x = DIG_X + i * 8 * DIG_SC + bit * DIG_SC
                    y = DIG_Y + row * DIG_SC
                    d.rectangle([x, y, x + DIG_SC - 1, y + DIG_SC - 1],
                                fill=255)


def glyphs(d, text, x, y, sc=1, fill=255):
    """Draw text with the character ROM, so it is the real Commodore font."""
    rom = open(CHARGEN, "rb").read()
    for i, ch in enumerate(text.upper()):
        code = ord(ch) - 0x40 if ch.isalpha() else ord(ch)
        if ch == " ":
            continue
        g = rom[code * 8:code * 8 + 8]
        for row in range(8):
            for bit in range(8):
                if g[row] & (0x80 >> bit):
                    px = x + i * 8 * sc + bit * sc
                    py = y + row * sc
                    d.rectangle([px, py, px + sc - 1, py + sc - 1], fill=fill)


def machine(d):
    """
    A breadbin 64.

    The first version drew it as a wireframe -- white outlines on black --
    and it read as a diagram rather than a machine. The real thing is a
    light beige wedge with DARK keys, so this fills the case solid and cuts
    the keys out of it in black. That one inversion does most of the work.

    The rest is the cues that say "Commodore" rather than "keyboard": the
    wedge profile with a raised back, the staggered rows and long space
    bar, the four function keys standing apart on the right, and the badge
    on the front lip.
    """
    x0, x1 = MACH_X0, MACH_X1
    top, deck, bot = MACH_TOP, MACH_FRONT, MACH_BOT
    inset = 20                  # the back edge sits in from the sides

    # --- the case, solid ---
    d.polygon([(x0 + inset, top), (x1 - inset, top),
               (x1, deck), (x0, deck)], fill=255)
    d.rectangle([x0, deck, x1, bot], fill=255)

    # seams: where the sloped back meets the deck, and the front lip
    lip = bot - 13
    d.line([(x0, deck), (x1, deck)], fill=0)
    d.line([(x0, lip), (x1, lip)], fill=0)
    # the chamfer down each side of the sloped back
    d.line([(x0 + inset, top), (x0, deck)], fill=0)
    d.line([(x1 - inset, top), (x1, deck)], fill=0)

    # --- keys, cut out dark ---
    kx0, ky0 = x0 + 9, deck + 5
    kx1, ky1 = x1 - 50, lip - 4
    cols, rows = 15, 5
    kw = (kx1 - kx0) / float(cols)
    kh = (ky1 - ky0) / float(rows)

    for r in range(rows):
        y = ky0 + r * kh
        y2 = y + kh - 2
        if r < 4:
            off = r * kw * 0.25      # each row steps right, as a real one does
            n = cols if r == 0 else cols - 1
            for c in range(n):
                x = kx0 + off + c * kw
                if x + kw - 2 > kx1:
                    break
                d.rectangle([int(x), int(y), int(x + kw - 2), int(y2)],
                            fill=0)
        else:
            # The bottom row of a C64 is ONE long space bar. The shift keys
            # live on the row above it, which the staggered loop already
            # draws.
            sx0 = kx0 + kw * 3.2
            sx1 = kx1 - kw * 2.2
            d.rectangle([int(sx0), int(y), int(sx1), int(y2)], fill=0)

    # the four function keys, set apart on the right
    fx0, fx1 = kx1 + 9, x1 - 11
    fh = (ky1 - ky0) / 4.0
    for r in range(4):
        y = ky0 + r * fh
        d.rectangle([fx0, int(y), fx1, int(y + fh - 3)], fill=0)

    # --- badge on the front lip: chevron, then the model name ---
    label = "commodore 64"
    bw = len(label) * 8 + 12
    bx, by = x1 - bw - 24, lip + 3
    for i in range(5):               # a chevron pointing right
        d.line([(bx + i, by + i), (bx + i, by + 9 - i)], fill=0)
    glyphs(d, label, bx + 10, by, fill=0)

    # power lamp, outboard of the badge
    d.rectangle([x1 - 16, lip + 5, x1 - 10, lip + 9], fill=0)


def pack(page):
    """320x200 mono -> c64 hires, cell order."""
    px = page.load()
    out = bytearray()
    for cy in range(H // 8):
        for cx in range(W // 8):
            for row in range(8):
                b = 0
                y = cy * 8 + row
                for bit in range(8):
                    if px[cx * 8 + bit, y] >= 128:
                        b |= 0x80 >> bit
                out.append(b)
    return bytes(out)


def rle(data):
    """(count, value) pairs, count 1..255, zero count ends it."""
    out = bytearray()
    i = 0
    while i < len(data):
        v = data[i]
        n = 1
        while i + n < len(data) and data[i + n] == v and n < 255:
            n += 1
        out.append(n)
        out.append(v)
        i += n
    out.append(0)
    return bytes(out)


def colourmap(logo_h):
    """One screen byte per text row: foreground<<4, background black."""
    rows = []
    for r in range(25):
        y = r * 8
        if y < DIG_Y - 2:
            c = C_LOGO
        elif y < MACH_TOP - 4:
            c = C_DIG
        else:
            c = C_MACH
        rows.append(c << 4)
    return bytes(rows)


if __name__ == "__main__":
    page = Image.new("L", (W, H), 0)
    logo_h = wordmark(page)
    d = ImageDraw.Draw(page)
    digits(d)
    machine(d)

    bmp = pack(page)
    packed = rle(bmp)
    cmap = colourmap(logo_h)

    open(os.path.join(HERE, "logo.bin"), "wb").write(packed)
    open(os.path.join(HERE, "logocol.bin"), "wb").write(cmap)
    page.point(lambda v: 255 if v >= 128 else 0).convert("1").resize(
        (640, 400), Image.NEAREST).save(os.path.join(HERE, "splash.png"))

    print("; wordmark %dx%d at y=%d" % (LOGO_W, logo_h, LOGO_Y))
    print("; bitmap %d -> RLE %d bytes (%.1f%%)"
          % (len(bmp), len(packed), 100.0 * len(packed) / len(bmp)))
    print("; colour map %d bytes (one per row)" % len(cmap))
