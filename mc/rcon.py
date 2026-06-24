"""Постоянный async-клиент Source RCON (без внешних зависимостей).

Держим ОДНО соединение и переиспользуем его: на каждый опрос не открываем
новый коннект (это троттлится на стороне сервера/облака и даёт таймауты).
Переподключаемся только при обрыве.

Протокол: size(int32) | id(int32) | type(int32) | body(ascii)\\0 \\0
"""
import asyncio
import struct

from config import config

_TYPE_AUTH = 3
_TYPE_COMMAND = 2
_TIMEOUT = 8  # сек на одну операцию (connect / чтение ответа)


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


class Rcon:
    def __init__(self) -> None:
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()  # сериализует доступ к одному сокету

    async def _connect(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(
            config.rcon_host, config.rcon_port
        )
        self._writer.write(_encode(1, _TYPE_AUTH, config.rcon_password))
        await self._writer.drain()
        resp_id, _, _ = await _read_packet(self._reader)
        if resp_id == -1:
            await self._close()
            raise PermissionError("RCON: неверный пароль")

    async def _close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        self._reader = self._writer = None

    async def command(self, cmd: str) -> str:
        async with self._lock:
            for attempt in (1, 2):  # одна попытка переподключиться
                try:
                    if self._writer is None:
                        await asyncio.wait_for(self._connect(), _TIMEOUT)
                    self._writer.write(_encode(2, _TYPE_COMMAND, cmd))
                    await self._writer.drain()
                    _, _, body = await asyncio.wait_for(
                        _read_packet(self._reader), _TIMEOUT
                    )
                    return body
                except PermissionError:
                    await self._close()
                    raise
                except Exception:
                    await self._close()  # сбросим битый коннект и переподключимся
                    if attempt == 2:
                        raise
            return ""

    async def close(self) -> None:
        async with self._lock:
            await self._close()


_rcon = Rcon()


async def rcon(command: str) -> str:
    """Выполнить консольную команду через постоянное соединение."""
    return await _rcon.command(command)


async def online_players() -> list[str]:
    """Список ников, кто сейчас онлайн (через команду `list`)."""
    resp = await rcon("list")
    # "There are 3 of a max of 20 players online: Alice, Bob, Carl"
    if ":" not in resp:
        return []
    names = resp.split(":", 1)[1].strip()
    return [n.strip() for n in names.split(",") if n.strip()]
