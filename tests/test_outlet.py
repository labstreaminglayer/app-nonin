from types import SimpleNamespace

import pytest

from nonin import outlet as module


@pytest.mark.parametrize("protocol,model,bits", [(2, "3012LP", 8), (7, "3017LP", 16)])
def test_stream_metadata(monkeypatch, protocol, model, bits):
    captured = {}
    monkeypatch.setattr(
        module,
        "StreamOutlet",
        lambda info, **kwargs: captured.update(info=info) or object(),
    )
    device = SimpleNamespace(protocol=protocol, model=model, serial_number="serial")
    module.create_stream_outlet(device)
    info = captured["info"]
    assert info.name() == "Nonin Medical Pulse Oximeter"
    assert info.type() == "PPG"
    assert info.channel_count() == 7
    assert info.nominal_srate() == 75
    assert info.source_id().startswith(f"Nonin_{model[:4]}_LP_USB_serial_")
    desc = info.desc()
    assert desc.child_value("selected_model") == model
    assert desc.child_value("data_format") == str(protocol)
    assert str(bits) in desc.child_value("sample_representation")
    assert "not sensor acquisition" in desc.child_value("timestamp_policy")
    assert "not detected" in desc.child_value("model_identity")
    channel = desc.child("channels").child("channel")
    for name in module.CHANNELS:
        assert channel.child_value("label") == name
        assert channel.child_value("unit") == "au"
        channel = channel.next_sibling()


def test_publish_order_timestamp_and_fault(monkeypatch):
    published = []

    class Device:
        packet_count = 1
        frame_count = 25
        last_timestamp = 123.5
        closed = 0

        def read(self):
            if not published:
                return dict(
                    reversed(list(zip(module.CHANNELS, [65535, 1, 2, 0, 1, 0, 1])))
                )
            raise ConnectionError("disconnected")

        def close(self):
            self.closed += 1

    device = Device()
    monkeypatch.setattr(
        module,
        "create_stream_outlet",
        lambda _: SimpleNamespace(
            push_sample=lambda values, timestamp: published.append((values, timestamp))
        ),
    )
    worker = module.Outlet(device)
    worker.start()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert published == [([65535, 1, 2, 0, 1, 0, 1], 123.5)]
    assert isinstance(worker.error, ConnectionError)
    assert device.closed == 1


def test_timeout_then_stop_is_not_a_fault(monkeypatch, caplog):
    class Device:
        packet_count = frame_count = 0
        closed = False

        def read(self):
            worker._stop_requested.set()
            raise TimeoutError()

        def close(self):
            self.closed = True

    device = Device()
    monkeypatch.setattr(module, "create_stream_outlet", lambda _: object())
    worker = module.Outlet(device)
    worker.start()
    worker.join(timeout=2)
    assert device.closed and worker.error is None
    assert "No valid samples" in caplog.text
