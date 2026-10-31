"""Serial interface for Nonin format 2 and format 7 devices."""

import logging
import os
import time
from collections import deque
from typing import Dict

from pylsl import local_clock
from serial import Serial, SerialException
from serial.tools.list_ports import comports

from .protocol import StreamDecoder

log = logging.getLogger(__name__)


def detect_nonin_devices():
    """Find candidate USB serial ports; USB identifiers do not identify a model."""
    devices = [p for p in comports() if p.vid == 1027 and p.pid == 24577]
    if not devices:
        raise ConnectionError("No Nonin candidate serial ports found")
    return devices


def validate_port(port: str = None):
    if port is None:
        device = detect_nonin_devices()[0]
        return device.device, device
    device = next(
        (p for p in comports() if os.path.realpath(p.device) == os.path.realpath(port)),
        None,
    )
    if device is None and not os.path.exists(port):
        raise ConnectionError(f"Serial port not found: {port}")
    return port, device


class Nonin:
    """A configured Nonin device. Reconnect requires a manual restart."""

    def __init__(self, port: str = None, baudrate=9600, protocol=2, timeout=1.0):
        if protocol not in (2, 7):
            raise ValueError("protocol must be 2 or 7")
        if timeout is None or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        import math

        if not math.isfinite(timeout):
            raise ValueError("timeout must be positive and finite")
        self.port, device = validate_port(port)
        self.protocol = protocol
        self.model = "3012LP" if protocol == 2 else "3017LP"
        self.manufacturer = getattr(device, "manufacturer", None) or "Nonin Medical"
        self.product = getattr(device, "product", None) or "Pulse Oximeter"
        self.serial_number = getattr(device, "serial_number", None) or "unknown"
        self.timeout = timeout
        self.packet_count = 0
        self.frame_count = 0
        self.last_timestamp = None
        self.decoder = StreamDecoder(protocol)
        self._pending = deque()
        self._closed = False
        try:
            self.serial = Serial(self.port, baudrate, timeout=timeout)
        except (SerialException, OSError) as exc:
            raise ConnectionError(f"Unable to open serial port {self.port}") from exc

    def read_frame(self):
        """Return the next validated canonical five-byte frame."""
        if self._closed:
            raise ConnectionError("Serial port is closed; restart the device")
        deadline = time.monotonic() + self.timeout
        while not self._pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.decoder.reset()
                raise TimeoutError("No complete validated sample before timeout")
            try:
                self.serial.timeout = remaining
                size = min(256, max(1, self.serial.in_waiting))
                data = self.serial.read(size)
                timestamp = local_clock()
            except (SerialException, OSError) as exc:
                log.error("Serial device disconnected: %s", exc)
                raise ConnectionError(
                    "Serial device disconnected; restart required"
                ) from exc
            if not data:
                self.decoder.reset()
                raise TimeoutError("No complete validated sample before timeout")
            frames = self.decoder.feed(data, timestamp)
            if len(frames) > 1:
                log.info("Buffered burst of %d validated frames", len(frames))
            self._pending.extend(frames)
        frame, self.last_timestamp = self._pending.popleft()
        self.frame_count += 1
        status = frame[1 if self.protocol == 2 else 0]
        if status & 1:
            self.packet_count += 1
        return frame

    def read(self) -> Dict[str, int]:
        frame = self.read_frame()
        if self.protocol == 2:
            status, pleth = frame[1], frame[2]
        else:
            status, pleth = frame[0], (frame[1] << 8) | frame[2]
        return {**self.parse_pleth(pleth), **self.parse_status(status)}

    @staticmethod
    def parse_status(status: int) -> Dict[str, int]:
        red, green = bool(status & 4), bool(status & 2)
        perfusion = {
            (False, False): 0,
            (True, False): 1,
            (True, True): 2,
            (False, True): 3,
        }[(red, green)]
        return {
            "Frame Sync": status & 1,
            "Perfusion Amplitude": perfusion,
            "Sensor Alarm": (status >> 3) & 1,
            "Out Of Track": (status >> 4) & 1,
            "Artifact - short term": (status >> 5) & 1,
            "Sensor disconnect": (status >> 6) & 1,
        }

    @staticmethod
    def parse_pleth(pleth: int) -> Dict[str, int]:
        return {"PPG": pleth}

    def close(self):
        if not self._closed:
            self._closed = True
            self.serial.close()
            log.info(
                "Serial session ended: frames=%d packets=%d discarded_bytes=%d rejected_aligned_frames=%d checksum_errors_aligned=%d resets=%d acquisitions=%d",
                self.frame_count,
                self.packet_count,
                self.decoder.discarded_bytes,
                self.decoder.rejected_frames,
                self.decoder.checksum_errors_aligned,
                self.decoder.resets,
                self.decoder.acquisitions,
            )

    def __str__(self):
        return f"{self.manufacturer} {self.product} {self.serial_number} at {self.port}"
