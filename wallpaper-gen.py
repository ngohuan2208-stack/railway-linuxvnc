#!/usr/bin/env python3
"""Generate a gradient wallpaper PNG (fast, bytearray).

Usage:
    wallpaper-gen.py [out] [w] [h] [r1 g1 b1 r2 g2 b2]

Colors are optional; defaults produce the classic dark midnight gradient.
"""
import os
import struct
import sys
import zlib


def create_png(width, height, c1=(10, 14, 23), c2=(30, 41, 59)):
    r1, g1, b1 = c1
    r2, g2, b2 = c2

    def chunk(ctype, data):
        c = ctype + data
        return struct.pack(">I", len(data)) + c + struct.pack(
            ">I", zlib.crc32(c) & 0xffffffff
        )

    xs = []
    for x in range(width):
        fx = x / width
        # horizontal lerp between the two colors + subtle vertical lift
        base_r = r1 + int((r2 - r1) * fx)
        base_g = g1 + int((g2 - g1) * fx)
        base_b = b1 + int((b2 - b1) * fx)
        xs.append((base_r, base_g, base_b))

    raw = bytearray()
    for y in range(height):
        fy = y / height
        gy = int(fy * 10)
        gb = int(fy * 15)
        raw.append(0)
        for r, g, b in xs:
            raw += bytes((min(r + 6, 255), min(g + gy, 255),
                          min(b + gb, 255)))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + chunk(b"IEND", b"")
    )


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "/opt/wallpaper.png"
    w = int(sys.argv[2]) if len(sys.argv) > 2 else 1600
    h = int(sys.argv[3]) if len(sys.argv) > 3 else 900
    if len(sys.argv) >= 10:
        c1 = tuple(int(x) % 256 for x in sys.argv[4:7])
        c2 = tuple(int(x) % 256 for x in sys.argv[7:10])
    else:
        c1, c2 = (10, 14, 23), (30, 41, 59)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    data = create_png(w, h, c1, c2)
    with open(out, "wb") as f:
        f.write(data)
    print(f"Wallpaper: {out} ({w}x{h}, {len(data)} bytes)")


if __name__ == "__main__":
    main()
