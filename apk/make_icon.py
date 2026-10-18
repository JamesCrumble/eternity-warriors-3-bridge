#!/usr/bin/env python3
"""Writes a neutral launcher icon (a shield on a dark tile) as PNG: the game's own artwork is not shipped.
  make_icon.py OUT.png [SIZE]"""
import struct
import sys
import zlib


def main():
    out, size = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 192
    rows = []
    cx = size / 2
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            t = y / size
            r, g, b = int(24 + 20 * t), int(32 + 30 * t), int(56 + 40 * t)
            u, v = abs(x - cx) / (size * 0.30), (y - size * 0.18) / (size * 0.64)
            if 0 <= v <= 1 and u <= 1 - max(0.0, v - 0.45) ** 2 * 3.3:
                edge = u > 0.86 or v < 0.05 or u > 1 - max(0.0, v - 0.45) ** 2 * 3.3 - 0.08
                r, g, b = (230, 190, 90) if edge else (170, 40, 40)
                if abs(x - cx) < size * 0.035 and 0.18 < v < 0.8:
                    r, g, b = 235, 235, 235
                if abs(y - size * (0.18 + 0.64 * 0.38)) < size * 0.03 and u < 0.45:
                    r, g, b = 235, 235, 235
            row += bytes((r, g, b))
        rows.append(bytes(row))

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)) \
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b"")
    open(out, "wb").write(png)


main()
