"""Independent synthetic PTY/LSL acceptance; execute against a pinned clone."""

import os
import threading
import time
import uuid
import pytest

pty = pytest.importorskip("pty")
from pylsl import local_clock
from nonin.device import Nonin

LABELS = [
    "PPG",
    "Frame Sync",
    "Perfusion Amplitude",
    "Sensor Alarm",
    "Out Of Track",
    "Artifact - short term",
    "Sensor disconnect",
]


def frame(fmt, value, status, aux=0):
    if fmt == 7:
        first = [status, value >> 8, value & 255, aux]
    else:
        first = [1, status, value, aux]
    return bytes(first + [sum(first) & 255])


def packets(fmt, count, start=0):
    return b"".join(
        frame(
            fmt,
            (start + i) % (65536 if fmt == 7 else 256),
            0x80 | (i % 25 == 0),
            (i * 43) & 255,
        )
        for i in range(count)
    )


class Rig:
    def __init__(self, fmt):
        self.master, slave = pty.openpty()
        self.path = os.ttyname(slave)
        self.slave = slave
        self.threads = []
        try:
            self.dev = Nonin(port=self.path, protocol=fmt, timeout=0.3)
            # Isolate repeated LSL discovery from earlier emulated devices.
            self.dev.serial_number = "pty-" + uuid.uuid4().hex
        except BaseException:
            os.close(self.master)
            os.close(self.slave)
            raise

    def send(self, blob, chunks=(4096,)):
        def write():
            pos = 0
            try:
                n = 0
                while pos < len(blob):
                    c = chunks[n % len(chunks)]
                    pos += os.write(self.master, blob[pos : pos + c])
                    n += 1
            except OSError:
                pass

        thread = threading.Thread(target=write, daemon=True)
        self.threads.append(thread)
        thread.start()
        return thread

    def close(self):
        self.dev.close()
        for fd in (self.master, self.slave):
            try:
                os.close(fd)
            except OSError:
                pass
        for thread in self.threads:
            thread.join(2)
            if thread.is_alive():
                raise RuntimeError("PTY writer did not terminate")


def collect(dev, n, deadline=8):
    samples, stamps = [], []
    until = time.monotonic() + deadline
    while len(samples) < n and time.monotonic() < until:
        try:
            samples.append(dev.read())
            stamps.append(dev.last_timestamp)
        except TimeoutError:
            continue
    return samples, stamps


@pytest.mark.parametrize("fmt", [2, 7])
def test_real_serial_chunking_and_status(fmt):
    rig = Rig(fmt)
    try:
        # Cover every status mask while preserving the 25-frame sync cadence.
        statuses = [0x80 | ((i % 64) << 1) | (i % 25 == 0) for i in range(300)]
        values = [
            (i * 997 if fmt == 7 else i * 13) % (65536 if fmt == 7 else 256)
            for i in range(300)
        ]
        data = b"".join(
            frame(fmt, v, s, (i * 43) & 255)
            for i, (v, s) in enumerate(zip(values, statuses))
        )
        writer = rig.send(data, (1, 2, 9, 3, 61, 5))
        samples, _ = collect(rig.dev, 100)
        writer.join(2)
        assert len(samples) >= 50
        for sample in samples:
            assert list(sample) == LABELS
            # Values identify their original frame uniquely for this prefix.
            matches = [
                i
                for i, v in enumerate(values)
                if v == sample["PPG"] and (statuses[i] & 1) == sample["Frame Sync"]
            ]
            assert matches
            assert any(
                sample["Perfusion Amplitude"]
                == {0: 0, 1: 3, 2: 1, 3: 2}[(statuses[i] >> 1) & 3]
                and [sample[k] for k in LABELS[3:]]
                == [(statuses[i] >> b) & 1 for b in (3, 4, 5, 6)]
                for i in matches
            )
    finally:
        rig.close()


def test_receive_completion_batch_timestamps():
    rig = Rig(7)
    try:
        before = local_clock()
        writer = rig.send(packets(7, 100))
        samples, stamps = collect(rig.dev, 50)
        writer.join(2)
        after = local_clock()
        assert len(samples) == 50
        assert all(before <= t <= after for t in stamps)
        assert stamps == sorted(stamps)
        assert len(set(stamps)) < len(
            stamps
        ), "buffered samples should retain the completion time of their serial read"
    finally:
        rig.close()


def test_checksum_and_byte_loss_recovery():
    rig = Rig(7)
    try:
        good = packets(7, 100, 2000)
        bad = bytearray(packets(7, 75, 3000))
        bad[5 * 30 + 4] ^= 0x01
        damaged = packets(7, 50, 4000)
        damaged = damaged[:111] + b"\x01" + damaged[111:190] + damaged[191:]
        tail = packets(7, 150, 5000)
        writer = rig.send(good + bad + damaged + tail, (2, 17, 1, 83))
        samples, _ = collect(rig.dev, 275, 10)
        writer.join(2)
        vals = [s["PPG"] for s in samples]
        assert vals and any(2000 <= x < 2100 for x in vals)
        assert 3030 not in vals, "checksum-corrupt frame was published"
        assert any(
            5000 <= x < 5150 for x in vals
        ), "did not recover after byte insertion/deletion"
        assert all(
            2000 <= x < 2100 or 3000 <= x < 3075 or 4000 <= x < 4050 or 5000 <= x < 5150
            for x in vals
        )
    finally:
        rig.close()


def test_timeout_disconnect_and_manual_restart():
    rig = Rig(7)
    try:
        rig.send(packets(7, 75)[:37]).join(2)
        with pytest.raises(TimeoutError):
            rig.dev.read()
        rig.send(packets(7, 100, 12000)).join(2)
        samples, _ = collect(rig.dev, 25)
        assert len(samples) == 25 and all(12000 <= x["PPG"] < 12100 for x in samples)
        os.close(rig.master)
        rig.master = -1
        disconnected_at = local_clock()
        # Already validated samples may remain buffered after the unplug.
        for _ in range(101):
            try:
                rig.dev.read()
                assert rig.dev.last_timestamp <= disconnected_at
            except ConnectionError:
                break
        else:
            pytest.fail("disconnect did not surface after draining buffered samples")
    finally:
        rig.close()
    second = Rig(7)
    try:
        second.send(packets(7, 100, 20000)).join(2)
        samples, _ = collect(second.dev, 25)
        assert len(samples) == 25 and all(20000 <= x["PPG"] < 20100 for x in samples)
    finally:
        second.close()


def test_actual_lsl_outlet_inlet_and_metadata():
    from pylsl import StreamInlet, resolve_byprop
    from nonin.outlet import Outlet

    rig = Rig(7)
    worker = Outlet(rig.dev)
    inlet = None
    try:
        worker.start()
        source = f'Nonin_3017_LP_USB_{rig.dev.serial_number}_{__import__("socket").gethostname()}'
        streams = resolve_byprop("source_id", source, timeout=6)
        assert streams, f"no LSL stream with source_id {source}"
        inlet = StreamInlet(streams[0])
        inlet.open_stream(timeout=5)
        info = inlet.info(timeout=5)
        xml = info.as_xml().lower()
        assert info.channel_count() == 7 and info.nominal_srate() == 75
        for key in (
            "selected_model",
            "data_format",
            "sample_representation",
            "timestamp_policy",
            "quality_flags",
            "sequence_counter",
        ):
            assert key in xml, key
        for label in LABELS:
            assert label.lower() in xml
        assert "3017" in xml and "float32" in xml
        before = local_clock()
        values = [0, 1, 255, 256, 257, 32768, 65281, 65535]
        blob = b"".join(
            frame(7, values[i % len(values)], 0x80 | (i % 25 == 0), (i * 43) & 255)
            for i in range(150)
        )
        writer = rig.send(blob, (4096,))
        received, timestamps = [], []
        until = time.monotonic() + 8
        while len(received) < 50 and time.monotonic() < until:
            sample, stamp = inlet.pull_sample(timeout=0.25)
            if sample is not None:
                received.append(sample)
                timestamps.append(stamp)
        writer.join(2)
        after = local_clock()
        assert len(received) >= 50
        assert set(values).issubset({int(s[0]) for s in received})
        assert all(len(s) == 7 and s[0] in values for s in received)
        assert all(before <= t <= after for t in timestamps)
        assert timestamps == sorted(timestamps)
        assert len(set(timestamps)) < len(timestamps)
        assert worker.error is None
    finally:
        worker.stop()
        worker.join(3)
        if inlet is not None:
            inlet.close_stream()
        rig.close()
    assert not worker.is_alive(), "worker did not terminate"


def test_cli_reports_connection_failure():
    import subprocess, sys

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "nonin",
            "--format",
            "7",
            "--port",
            "/dev/definitely-nonin-missing",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert result.stdout.strip() or result.stderr.strip()


def test_worker_disconnect_exposes_error():
    from nonin.outlet import Outlet

    rig = Rig(7)
    worker = Outlet(rig.dev)
    try:
        worker.start()
        os.close(rig.master)
        rig.master = -1
        worker.join(4)
        assert not worker.is_alive()
        assert isinstance(worker.error, ConnectionError), repr(worker.error)
    finally:
        worker.stop()
        worker.join(3)
        rig.close()
