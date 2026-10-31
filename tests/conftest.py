from collections import deque
from types import SimpleNamespace

import pytest


def frame(protocol, value=0, index=0, flags=0, aux=0):
    status = 0x80 | flags | (index == 0)
    if protocol == 2:
        data = [1, status, value & 255, aux]
    else:
        data = [status, value >> 8, value & 255, aux]
    return bytes(data + [sum(data) & 255])


def packet(protocol, start=0):
    return b"".join(
        frame(
            protocol,
            (start + i) % (256 if protocol == 2 else 65536),
            i,
            aux=(128 + i) % 256,
        )
        for i in range(25)
    )


class FakeSerial:
    def __init__(self, chunks):
        self.chunks = deque(chunks)
        self.timeout = 1
        self.closed = False
        self.close_count = 0

    @property
    def in_waiting(self):
        return (
            len(self.chunks[0])
            if self.chunks and isinstance(self.chunks[0], bytes)
            else 0
        )

    def read(self, n):
        if not self.chunks:
            return b""
        item = self.chunks.popleft()
        if isinstance(item, Exception):
            raise item
        self.chunks.appendleft(item[n:]) if len(item) > n else None
        return item[:n]

    def close(self):
        self.closed = True
        self.close_count += 1


@pytest.fixture
def make_device(monkeypatch):
    import nonin.device as device

    def create(chunks, protocol=2, times=None):
        fake = FakeSerial(chunks)
        monkeypatch.setattr(
            device,
            "validate_port",
            lambda port: (
                port or "/dev/mock",
                SimpleNamespace(serial_number="123", manufacturer=None, product=None),
            ),
        )
        monkeypatch.setattr(device, "Serial", lambda *args, **kwargs: fake)
        if times is not None:
            ticks = iter(times)
            monkeypatch.setattr(device, "local_clock", lambda: next(ticks))
        return device.Nonin(protocol=protocol), fake

    return create
