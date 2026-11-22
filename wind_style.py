"""Restyle DWD wind barbs for a dimmed basemap.

DWD renders black barbs for a light map. The wind map dims the basemap, so the
barbs must be light. This module recolours the alpha mask to white and lifts the
antialiased strokes. It uses only the standard library.
"""
import struct
import zlib

from image_validation import PNG

WHITE = b"\xff\xff\xff"
# DWD draws thin antialiased strokes. A modest lift keeps them crisp on the
# dimmed map without turning the barbs into blobs.
ALPHA_LIFT = 1.5


def _paeth(a, b, c):
    estimate = a + b - c
    pa, pb, pc = abs(estimate - a), abs(estimate - b), abs(estimate - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _unfilter(raw, width, height):
    """Reverse the PNG row filters for 8-bit RGBA scanlines."""
    stride = width * 4
    pixels = bytearray(height * stride)
    position = 0
    previous = bytearray(stride)
    for row_index in range(height):
        filter_type = raw[position]
        position += 1
        row = bytearray(raw[position:position + stride])
        position += stride
        if filter_type == 1:
            for index in range(4, stride):
                row[index] = (row[index] + row[index - 4]) & 255
        elif filter_type == 2:
            for index in range(stride):
                row[index] = (row[index] + previous[index]) & 255
        elif filter_type == 3:
            for index in range(stride):
                left = row[index - 4] if index >= 4 else 0
                row[index] = (row[index] + ((left + previous[index]) >> 1)) & 255
        elif filter_type == 4:
            for index in range(stride):
                left = row[index - 4] if index >= 4 else 0
                above = previous[index]
                upper_left = previous[index - 4] if index >= 4 else 0
                row[index] = (row[index] + _paeth(left, above, upper_left)) & 255
        elif filter_type != 0:
            raise ValueError("Invalid wind image filter")
        pixels[row_index * stride:(row_index + 1) * stride] = row
        previous = row
    return pixels


def _chunk(kind, body):
    return (struct.pack(">I", len(body)) + kind + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff))


def restyle(data):
    """Return a PNG with white barbs, or the input when it is already white."""
    if not isinstance(data, bytes) or not data.startswith(PNG):
        raise ValueError("Invalid wind image")
    offset, header, compressed = 8, None, bytearray()
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        body = data[offset + 8:offset + 8 + length]
        offset += length + 12
        if kind == b"IHDR":
            header = body
        elif kind == b"IDAT":
            compressed.extend(body)
        elif kind == b"IEND":
            break
    if header is None or not compressed:
        raise ValueError("Invalid wind image")
    width, height, depth, colour, compression, filtering, interlace = struct.unpack(">IIBBBBB", header)
    if (depth, colour, compression, filtering, interlace) != (8, 6, 0, 0, 0):
        raise ValueError("Unsupported wind image")
    raw = zlib.decompress(compressed)
    stride = width * 4
    if len(raw) != height * (stride + 1):
        raise ValueError("Invalid wind image size")
    pixels = _unfilter(raw, width, height)
    black = False
    for index in range(0, len(pixels), 4):
        alpha = pixels[index + 3]
        if alpha and pixels[index:index + 3] != WHITE:
            black = True
        if alpha:
            pixels[index:index + 3] = WHITE
            pixels[index + 3] = min(255, int(alpha * ALPHA_LIFT))
    if not black:
        return data
    encoded = bytearray()
    for row in range(height):
        encoded.append(0)
        encoded.extend(pixels[row * stride:(row + 1) * stride])
    return (PNG + _chunk(b"IHDR", header)
            + _chunk(b"IDAT", zlib.compress(bytes(encoded), 9))
            + _chunk(b"IEND", b""))
