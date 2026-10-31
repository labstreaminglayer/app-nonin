"""Bounded streaming decoder for Nonin serial formats 2 and 7.

Synchronization requires a complete 25-frame packet. Once locked, every frame
must have a valid checksum and the expected sync bit. A failure returns to packet
acquisition; this cannot detect every possible loss without sequence numbers.
"""

import logging
from collections import deque

log = logging.getLogger(__name__)


class StreamDecoder:
    def __init__(self, protocol=2):
        if protocol not in (2, 7):
            raise ValueError("protocol must be 2 or 7")
        self.protocol = protocol
        self._bytes = deque()
        self._times = deque()
        self.locked = False
        self._index = 0
        self.discarded_bytes = 0
        self.rejected_frames = 0
        self.checksum_errors_aligned = 0
        self.resets = 0
        self.acquisitions = 0

    def _valid(self, frame, index):
        status = frame[1 if self.protocol == 2 else 0]
        return (
            len(frame) == 5
            and (self.protocol != 2 or frame[0] == 1)
            and status & 0x80
            and bool(status & 1) == (index == 0)
            and sum(frame[:4]) % 256 == frame[4]
        )

    def _drop(self, count):
        for _ in range(count):
            self._bytes.popleft()
            self._times.popleft()

    def reset(self):
        """Discard incomplete input and require a fresh packet after a stall."""
        self.discarded_bytes += len(self._bytes)
        self._bytes.clear()
        self._times.clear()
        self.locked = False
        self._index = 0
        self.resets += 1
        log.warning("Serial stream stalled; decoder reset")

    def feed(self, data, timestamp):
        """Return validated (canonical frame, receive timestamp) pairs.

        The timestamp belongs to the read that delivered each frame's last byte.
        Processing one byte at a time limits retained state to 125 bytes.
        """
        result = []
        for byte in data:
            self._bytes.append(byte)
            self._times.append(timestamp)
            if not self.locked:
                if len(self._bytes) < 125:
                    continue
                candidate = list(self._bytes)
                if all(self._valid(candidate[i * 5 : i * 5 + 5], i) for i in range(25)):
                    times = list(self._times)
                    result.extend(
                        (bytes(candidate[i * 5 : i * 5 + 5]), times[i * 5 + 4])
                        for i in range(25)
                    )
                    self._drop(125)
                    self.locked = True
                    self._index = 0
                    self.acquisitions += 1
                    log.info(
                        "Acquired serial packet synchronization: acquisitions=%d discarded_bytes=%d rejected_aligned_frames=%d resets=%d",
                        self.acquisitions,
                        self.discarded_bytes,
                        self.rejected_frames,
                        self.resets,
                    )
                else:
                    self._drop(1)
                    self.discarded_bytes += 1
            elif len(self._bytes) == 5:
                frame = bytes(self._bytes)
                if self._valid(frame, self._index):
                    result.append((frame, self._times[-1]))
                    self._drop(5)
                    self._index = (self._index + 1) % 25
                else:
                    self.rejected_frames += 1
                    if sum(frame[:4]) % 256 != frame[4]:
                        self.checksum_errors_aligned += 1
                    self.locked = False
                    self._index = 0
                    self._drop(1)
                    self.discarded_bytes += 1
                    log.warning(
                        "Rejected serial frame; checksum_errors_aligned=%d; reacquiring packet synchronization",
                        self.checksum_errors_aligned,
                    )
        return result
