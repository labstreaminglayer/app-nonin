import pytest
from serial import SerialException
from nonin.device import Nonin
from conftest import frame, packet


@pytest.mark.parametrize("protocol", [2, 7])
def test_read_order_values_and_buffered_timestamps(make_device, protocol):
    data = packet(protocol, 1)
    device, _ = make_device([data[:7], data[7:10], data[10:]], protocol, [11, 12, 13])
    sample = device.read()
    assert list(sample) == [
        "PPG",
        "Frame Sync",
        "Perfusion Amplitude",
        "Sensor Alarm",
        "Out Of Track",
        "Artifact - short term",
        "Sensor disconnect",
    ]
    assert sample["PPG"] == 1
    assert device.last_timestamp == 11
    assert device.read_frame() == frame(protocol, 2, 1, aux=129)
    assert device.last_timestamp == 12
    assert device.packet_count == 1 and device.frame_count == 2
    assert device.model == ("3012LP" if protocol == 2 else "3017LP")


def test_status_and_format7_full_value(make_device):
    flags = 0x7E
    data = b"".join(frame(7, 0xF123, i, flags, 255) for i in range(25))
    device, _ = make_device([data], 7)
    assert device.read() == {
        "PPG": 0xF123,
        "Frame Sync": 1,
        "Perfusion Amplitude": 2,
        "Sensor Alarm": 1,
        "Out Of Track": 1,
        "Artifact - short term": 1,
        "Sensor disconnect": 1,
    }
    assert [
        Nonin.parse_status(0x80 | x)["Perfusion Amplitude"] for x in (0, 4, 6, 2)
    ] == [0, 1, 2, 3]


def test_stall_resets_partial_input_and_reacquires(make_device):
    device, fake = make_device([packet(2)[:70], b""])
    with pytest.raises(TimeoutError):
        device.read()
    assert device.decoder.resets == 1
    fake.chunks.extend([packet(2, 50)])
    assert device.read()["PPG"] == 50


def test_disconnect_close_and_manual_restart(make_device):
    device, fake = make_device([SerialException("unplugged")], 7)
    with pytest.raises(ConnectionError):
        device.read()
    device.close()
    device.close()
    assert fake.close_count == 1
    with pytest.raises(ConnectionError):
        device.read()
    restarted, _ = make_device([packet(7, 500)], 7)
    assert restarted.read()["PPG"] == 500


def test_invalid_config():
    with pytest.raises(ValueError):
        Nonin(protocol=8)
    with pytest.raises(ValueError):
        Nonin(timeout=0)


def test_stable_port_alias_preserves_usb_identity(monkeypatch, tmp_path):
    from types import SimpleNamespace
    import nonin.device as module

    target = tmp_path / "ttyUSB0"
    target.touch()
    alias = tmp_path / "device-by-id"
    alias.symlink_to(target)
    metadata = SimpleNamespace(device=str(target), serial_number="device-123")
    monkeypatch.setattr(module, "comports", lambda: [metadata])
    port, device = module.validate_port(str(alias))
    assert port == str(alias)
    assert device.serial_number == "device-123"
