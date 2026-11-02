"""Original CC0 business illustrations, reproducible with the standard library only."""
import math
import struct
import zlib
from pathlib import Path

W, H = 540, 960
root = Path(__file__).resolve().parents[1] / "assets/visuals"


def png(path, pixels):
    def chunk(name, data):
        return struct.pack('>I', len(data)) + name + data + struct.pack('>I', zlib.crc32(name + data))
    raw = b''.join(b'\0' + bytes(pixels[y * W * 3:(y + 1) * W * 3]) for y in range(H))
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', W, H, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


def image(kind):
    pixels = bytearray()
    top, bottom = ((14, 28, 44), (33, 67, 76)) if kind != 1 else ((54, 42, 35), (23, 29, 38))
    for y in range(H):
        t = y / H
        for x in range(W):
            glow = 16 * math.exp(-((x - 400) ** 2 + (y - 290) ** 2) / 90000)
            pixels.extend(int(min(255, a * (1 - t) + b * t + glow)) for a, b in zip(top, bottom))
    def rect(x1, y1, x2, y2, color):
        for y in range(max(0, y1), min(H, y2)):
            pixels[(y * W + x1) * 3:(y * W + x2) * 3] = bytes(color) * (x2 - x1)
    def disc(cx, cy, radius, color):
        for y in range(max(0, cy - radius), min(H, cy + radius)):
            dx = int(math.sqrt(max(0, radius ** 2 - (y - cy) ** 2)))
            rect(max(0, cx - dx), y, min(W, cx + dx), y + 1, color)
    mint, cream, gold = (104, 185, 168), (211, 208, 190), (188, 145, 89)
    # Quiet linework and offset shadows make each scene distinct while keeping contrast.
    if kind == 0:
        rect(112, 350, 442, 695, (10, 23, 32)); rect(94, 330, 424, 675, cream)
        rect(118, 362, 400, 374, gold)
        for y, width in ((413, 233), (446, 190), (479, 222), (544, 175), (577, 220)):
            rect(120, y, 120 + width, y + 7, (100, 118, 116))
        disc(356, 617, 28, mint)
    elif kind == 1:
        rect(107, 420, 443, 700, (15, 23, 28)); rect(90, 400, 420, 680, gold)
        rect(236, 400, 275, 680, (218, 191, 145)); rect(90, 400, 420, 422, (215, 174, 116))
        rect(120, 477, 213, 548, cream)
        for x in range(128, 205, 9): rect(x, 496, x + 3, 532, (36, 52, 59))
        disc(397, 360, 54, mint); rect(375, 354, 420, 363, (25, 58, 62))
    else:
        rect(73, 365, 468, 697, (12, 27, 41)); rect(65, 350, 460, 680, (43, 67, 82))
        for y in range(400, 640, 60): rect(95, y, 430, y + 2, (65, 88, 98))
        for x, height in ((126, 95), (202, 150), (278, 120), (354, 220)):
            rect(x, 640 - height, x + 42, 640, mint if x != 354 else gold)
        disc(410, 332, 40, cream)
    png(root / f'{kind + 2:02}-business.png', pixels)


for kind in range(3): image(kind)
