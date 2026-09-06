"""Small bounded protobuf / gRPC-Web codec for the official local IoT service."""
from __future__ import annotations

import struct
from typing import BinaryIO

MAX_FRAME = 1024 * 1024


def varint(value: int) -> bytes:
    if value < 0:
        value &= (1 << 64) - 1
    out = bytearray()
    while value >= 128:
        out.append((value & 127) | 128)
        value >>= 7
    out.append(value)
    return bytes(out)


def field(number: int, value: int | bytes | str) -> bytes:
    if isinstance(value, str):
        value = value.encode("utf-8")
    if isinstance(value, bytes):
        return varint(number * 8 + 2) + varint(len(value)) + value
    return varint(number * 8) + varint(value)


def decode(data: bytes) -> dict[int, list[int | bytes]]:
    if len(data) > MAX_FRAME:
        raise ValueError("protobuf message too large")
    pos = 0
    result: dict[int, list[int | bytes]] = {}

    def read_varint() -> int:
        nonlocal pos
        value = 0
        for shift in range(0, 70, 7):
            if pos >= len(data):
                raise ValueError("truncated varint")
            part = data[pos]
            pos += 1
            value |= (part & 127) << shift
            if not part & 128:
                return value
        raise ValueError("oversized varint")

    while pos < len(data):
        tag = read_varint()
        number, wire = tag >> 3, tag & 7
        if not number:
            raise ValueError("invalid field zero")
        if wire == 0:
            value = read_varint()
        elif wire in (1, 2, 5):
            size = read_varint() if wire == 2 else (8 if wire == 1 else 4)
            if pos + size > len(data):
                raise ValueError("truncated field")
            value = data[pos:pos + size]
            pos += size
        else:
            raise ValueError("unsupported wire type")
        result.setdefault(number, []).append(value)
    return result


def first(message: dict, number: int, default=None):
    return message.get(number, [default])[0]


def signed32(number: int) -> int:
    number &= 0xFFFFFFFF
    return number - (1 << 32) if number & (1 << 31) else number


def frame(payload: bytes) -> bytes:
    return b"\0" + struct.pack(">I", len(payload)) + payload


def read_exact(stream: BinaryIO, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            raise EOFError("IoT stream closed")
        data.extend(chunk)
    return bytes(data)


def read_frame(stream: BinaryIO) -> tuple[int, bytes]:
    header = read_exact(stream, 5)
    size = struct.unpack(">I", header[1:])[0]
    if size > MAX_FRAME:
        raise ValueError("IoT frame too large")
    if header[0] not in (0, 128):
        raise ValueError("unsupported compressed IoT frame")
    return header[0], read_exact(stream, size)


def check_trailer(payload: bytes) -> None:
    values = {}
    for line in payload.decode("ascii", errors="replace").splitlines():
        key, sep, value = line.partition(":")
        if sep:
            values[key.strip().lower()] = value.strip()
    if values.get("grpc-status") != "0":
        raise OSError(f"IoT RPC failed: {values.get('grpc-message', values.get('grpc-status', 'missing status'))}")
