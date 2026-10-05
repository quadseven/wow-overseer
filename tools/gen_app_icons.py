"""The Home Screen icons, drawn from the site's own mark.

The mark is a vermilion dot beside the name (index.html, `.mark .dot`). An
icon has no room for the name, so the icon is the dot on the dark ground the
realm band and the dark theme already use. iOS rounds the corners itself and
Android masks to its own shape, so the square is drawn full bleed and the dot
sits well inside the maskable safe zone (the central 80%).

Pure standard library on purpose: the image ships no imaging package and this
is run by hand, so a PNG writer of thirty lines beats a new dependency.

Run from the repo root:  python3 tools/gen_app_icons.py
Writes apple-touch-icon.png (180), icon-192.png and icon-512.png.
"""

from __future__ import annotations

import pathlib
import struct
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
GROUND = (0x0A, 0x14, 0x0E)  # the dark theme's ground, --bg in index.html
DOT = (0xFF, 0x4D, 0x2E)  # --vermilion
# The dot's diameter as a share of the icon. The mark's dot is small beside a
# word; alone on a tile it needs presence without crowding the rounded corner.
DOT_SHARE = 0.42
SUPERSAMPLE = 4

SIZES = {"apple-touch-icon.png": 180, "icon-192.png": 192, "icon-512.png": 512}


def _chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def draw(size: int) -> bytes:
    """One opaque RGB PNG: the ground, and the dot antialiased by coverage."""
    centre = size / 2
    radius = size * DOT_SHARE / 2
    step = 1 / SUPERSAMPLE
    rows = []
    for y in range(size):
        row = bytearray([0])  # filter type 0 for every scanline
        for x in range(size):
            hits = 0
            for sy in range(SUPERSAMPLE):
                for sx in range(SUPERSAMPLE):
                    dx = x + (sx + 0.5) * step - centre
                    dy = y + (sy + 0.5) * step - centre
                    if dx * dx + dy * dy <= radius * radius:
                        hits += 1
            a = hits / (SUPERSAMPLE * SUPERSAMPLE)
            row.extend(round(g + (d - g) * a) for g, d in zip(GROUND, DOT))
        rows.append(bytes(row))
    raw = b"".join(rows)
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


def main() -> None:
    for name, size in SIZES.items():
        (ROOT / name).write_bytes(draw(size))
        print(name, size)


if __name__ == "__main__":
    main()
