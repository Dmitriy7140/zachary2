"""Минимальный async-клиент Source RCON (без внешних зависимостей).

Протокол: https://wiki.vg/RCON
Пакет (little-endian): size(int32) | id(int32) | type(int32) | body(ascii)\\0 \\0
"""
import asyncio
import struct

from config import config

_TYPE_AUTH = 3
_TYPE_COMMAND = 2


def _encode(req_id: int, req_type: int, body: str) -> bytes:
    payload = struct.pack("<ii", req_id, req_type) + body.encode("utf-8") + b"\x00\x00"
    return struct.pack("<i", len(payload)) + payload


async def _read_packet(reader: asyncio.StreamReader) -> tuple[int, int, str]:
    raw_len = await reader.readexactly(4)
    (length,) = struct.unpack("<i", raw_len)
    data = await reader.readexactly(length)
    req_id, req_type = struct.unpack("<ii", data[:8])
    body = data[8:-2].decode("utf-8", errors="replace")
    return req_id, req_type, body


async def rcon(command: str) -> str:
    """Подключиться, авторизоваться, выполнить команду, вернуть ответ."""
    reader, writer = await asyncio.open_connection(config.rcon_host, config.rcon_port)
    try:
        # авторизация
        writer.write(_encode(1, _TYPE_AUTH, config.rcon_password))
        await writer.drain()
        resp_id, _, _ = await _read_packet(reader)
        if resp_id == -1:
            raise PermissionError("RCON: неверный пароль")

        # команда
        writer.write(_encode(2, _TYPE_COMMAND, command))
        await writer.drain()
        _, _, body = await _read_packet(reader)
        return body
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def online_players() -> list[str]:
    """Список ников, кто сейчас онлайн (через команду `list`)."""
    resp = await rcon("list")
    # "There are 3 of a max of 20 players online: Alice, Bob, Carl"
    if ":" not in resp:
        return []
    names = resp.split(":", 1)[1].strip()
    return [n.strip() for n in names.split(",") if n.strip()]
