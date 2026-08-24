#!/usr/bin/env python3
"""Generate a gradient wallpaper for XFCE desktop."""
import os
import sys
import struct
import zlib

def create_png(width, height, pixels):
    def chunk(ctype, data):
        c = ctype + data
        crc = struct.pack(">I", zlib.crc32(c) & 0xffffffff)
        return struct.pack(">I", len(data)) + c + crc

    header = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))

    raw = b""
    for y in range(height):
        raw += b"\x00"
        for x in range(width):
            r = int(10 + (x / width) * 20)
            g = int(12 + (y / height) * 18)
            b = int(30 + ((x + y) / (width + height)) * 35)
            raw += bytes([min(r, 255), min(g, 255), min(b, 255)])

    idat = chunk(b"IDAT", zlib.compress(raw, 9))
    iend = chunk(b"IEND", b"")
    return header + ihdr + idat + iend


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "/home/user/.wallpapers/default.png"
    w = int(sys.argv[2]) if len(sys.argv) > 2 else 1920
    h = int(sys.argv[3]) if len(sys.argv) > 3 else 1080
    os.makedirs(os.path.dirname(out), exist_ok=True)
    data = create_png(w, h, None)
    with open(out, "wb") as f:
        f.write(data)
    print(f"Wallpaper: {out} ({w}x{h}, {len(data)} bytes)")


if __name__ == "__main__":
    main()
