#!/usr/bin/env python3
"""Generate a gradient wallpaper (fast, bytearray)."""
import os
import struct
import sys
import zlib


def create_png(width, height):
    def chunk(ctype, data):
        c = ctype + data
        return struct.pack(">I", len(data)) + c + struct.pack(
            ">I", zlib.crc32(c) & 0xffffffff
        )

    # precompute per-x base colors
    xs = []
    for x in range(width):
        fx = x / width
        xs.append((int(10 + fx * 20), int(12 + fx * 8), int(30 + fx * 20)))

    raw = bytearray()
    for y in range(height):
        fy = y / height
        gy = int(fy * 10)
        gb = int(fy * 15)
        raw.append(0)
        for r, g, b in xs:
            raw += bytes((r, g + gy, min(b + gb, 255)))

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
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    data = create_png(w, h)
    with open(out, "wb") as f:
        f.write(data)
    print(f"Wallpaper: {out} ({w}x{h}, {len(data)} bytes)")


if __name__ == "__main__":
    main()
