#!/usr/bin/env python3
"""Losslessly shrink the PNGs that gen-web-icons.sh rasterizes.

macOS `sips` writes every row with filter type 0 and always keeps an alpha
channel, which on a smooth gradient costs about 4.5x: the 512px app icon lands
at 243 kB where the same pixels re-encoded take 54 kB. rsvg-convert and cairosvg
are better but not optimal either, and pngquant/optipng are not installed
anywhere in this toolchain, so this does the two things that matter with nothing
but the standard library:

  * drop the alpha channel when every pixel is already opaque (the app icons are
    full-bleed; the favicon's rounded corners are not, and keep theirs)
  * pick the cheapest of the five PNG filters per row, then deflate at level 9

No pixel values change. The RGB planes are compared against the input before
anything is written back, so a bug here fails loudly rather than quietly
degrading an icon.
"""

import os
import struct
import sys
import zlib

# (channels, has_alpha) by PNG colour type. Only what sips and rsvg emit.
COLOR_TYPES = {2: (3, False), 6: (4, True)}


def _unfilter(raw: bytes, width: int, height: int, bpp: int) -> list[bytes]:
    stride = width * bpp
    rows: list[bytes] = []
    prev = bytearray(stride)
    pos = 0
    for _ in range(height):
        ftype = raw[pos]
        pos += 1
        line = bytearray(raw[pos : pos + stride])
        pos += stride
        for x in range(stride):
            left = line[x - bpp] if x >= bpp else 0
            up = prev[x]
            upleft = prev[x - bpp] if x >= bpp else 0
            if ftype == 1:
                line[x] = (line[x] + left) & 0xFF
            elif ftype == 2:
                line[x] = (line[x] + up) & 0xFF
            elif ftype == 3:
                line[x] = (line[x] + (left + up) // 2) & 0xFF
            elif ftype == 4:
                p = left + up - upleft
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - upleft)
                pred = left if (pa <= pb and pa <= pc) else (up if pb <= pc else upleft)
                line[x] = (line[x] + pred) & 0xFF
        rows.append(bytes(line))
        prev = line
    return rows


def _filter_row(line: bytes, prev: bytes, bpp: int) -> bytes:
    """Emit the row under whichever filter minimises the sum of absolute
    differences — the heuristic the PNG spec itself suggests."""
    best: tuple[int, int, bytearray] | None = None
    for ftype in range(5):
        cand = bytearray(len(line))
        for x in range(len(line)):
            left = line[x - bpp] if x >= bpp else 0
            up = prev[x]
            upleft = prev[x - bpp] if x >= bpp else 0
            if ftype == 0:
                v = line[x]
            elif ftype == 1:
                v = line[x] - left
            elif ftype == 2:
                v = line[x] - up
            elif ftype == 3:
                v = line[x] - (left + up) // 2
            else:
                p = left + up - upleft
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - upleft)
                v = line[x] - (left if (pa <= pb and pa <= pc) else (up if pb <= pc else upleft))
            cand[x] = v & 0xFF
        score = sum(min(v, 256 - v) for v in cand)
        if best is None or score < best[0]:
            best = (score, ftype, cand)
    assert best is not None
    return bytes([best[1]]) + bytes(best[2])


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    )


def read_png(path: str) -> tuple[int, int, int, list[bytes]]:
    """Return (width, height, bytes-per-pixel, unfiltered rows)."""
    data = open(path, "rb").read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit(f"{path}: not a PNG")
    pos, idat, header = 8, b"", None
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        tag = data[pos + 4 : pos + 8]
        payload = data[pos + 8 : pos + 8 + length]
        if tag == b"IHDR":
            header = struct.unpack(">IIBBBBB", payload)
        elif tag == b"IDAT":
            idat += payload
        pos += 12 + length
    if header is None:
        raise SystemExit(f"{path}: no IHDR")
    width, height, depth, ctype, _, _, interlace = header
    if depth != 8 or interlace != 0 or ctype not in COLOR_TYPES:
        raise SystemExit(f"{path}: unsupported PNG (depth {depth}, type {ctype})")
    bpp = COLOR_TYPES[ctype][0]
    return width, height, bpp, _unfilter(zlib.decompress(idat), width, height, bpp)


def optimize(path: str) -> tuple[int, int]:
    width, height, bpp, rows = read_png(path)

    opaque = bpp == 3 or all(
        row[x] == 0xFF for row in rows for x in range(3, len(row), 4)
    )
    if bpp == 4 and opaque:
        rows = [
            bytes(b for x in range(0, len(row), 4) for b in row[x : x + 3]) for row in rows
        ]
        out_bpp = 3
    else:
        out_bpp = bpp

    stride = width * out_bpp
    body = bytearray()
    prev = bytes(stride)
    for row in rows:
        body += _filter_row(row, prev, out_bpp)
        prev = row

    ctype = 2 if out_bpp == 3 else 6
    png = b"\x89PNG\r\n\x1a\n"
    png += _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, ctype, 0, 0, 0))
    png += _chunk(b"IDAT", zlib.compress(bytes(body), 9))
    png += _chunk(b"IEND", b"")

    before = len(open(path, "rb").read())
    tmp = path + ".opt"
    open(tmp, "wb").write(png)

    # Verify before replacing: same dimensions, same visible pixels.
    vw, vh, _, vrows = read_png(tmp)
    if (vw, vh) != (width, height) or vrows != rows:
        os.unlink(tmp)
        raise SystemExit(f"{path}: re-encode changed the image, refusing to write")

    os.replace(tmp, path)
    return before, len(png)


def main(paths: list[str]) -> int:
    for path in paths:
        before, after = optimize(path)
        saved = 100 * (before - after) // before if before else 0
        print(f"  {path.rsplit('/', 1)[-1]:<24} {before:>7} -> {after:>7} bytes  (-{saved}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
