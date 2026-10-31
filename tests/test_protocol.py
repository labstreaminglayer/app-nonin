import random
import pytest
from nonin.protocol import StreamDecoder
from conftest import frame, packet


@pytest.mark.parametrize("protocol", [2, 7])
def test_chunking_and_canonical_frames(protocol):
    data = b"junk\x01\x80" + packet(protocol, 10) + packet(protocol, 35)
    expected = [frame(protocol, 10 + i, i % 25, aux=128 + i % 25) for i in range(50)]
    for size in (1, 2, 4, 5, 17, 124, 125, 4096):
        decoder = StreamDecoder(protocol)
        output = []
        for i in range(0, len(data), size):
            output.extend(decoder.feed(data[i : i + size], i))
            assert len(decoder._bytes) <= 124
        assert [f for f, _ in output] == expected
        assert decoder.discarded_bytes == 6


def test_exhaustive_16_bit_values_and_byte_order():
    decoder = StreamDecoder(7)
    data = b"".join(
        frame(7, value, value % 25, aux=(value * 7) % 256) for value in range(65536)
    )
    output = decoder.feed(data, 3.0)
    assert len(output) == 65536
    assert [(f[1] << 8) | f[2] for f, _ in output] == list(range(65536))


@pytest.mark.parametrize("protocol", [2, 7])
@pytest.mark.parametrize("kind", ["insert", "delete", "corrupt", "sync"])
def test_recovery_after_damage(protocol, kind):
    good = packet(protocol, 0)
    damaged = bytearray(packet(protocol, 25))
    if kind == "insert":
        damaged.insert(17, 0x42)
    elif kind == "delete":
        del damaged[17]
    elif kind == "corrupt":
        damaged[17] ^= 1
    else:
        pos = 5 * 3 + (1 if protocol == 2 else 0)
        damaged[pos] |= 1
        damaged[5 * 3 + 4] = sum(damaged[5 * 3 : 5 * 3 + 4]) & 255
    decoder = StreamDecoder(protocol)
    output = decoder.feed(
        good + damaged + packet(protocol, 50) + packet(protocol, 75), 1
    )
    values = [f[2] if protocol == 2 else (f[1] << 8 | f[2]) for f, _ in output]
    assert values[:25] == list(range(25))
    assert values[-50:] == list(range(50, 100))
    assert decoder.rejected_frames >= 1
    if kind == "corrupt":
        assert decoder.checksum_errors_aligned >= 1
    assert decoder.acquisitions >= 2


def test_timestamp_tracks_last_byte_not_packet_release():
    decoder = StreamDecoder(7)
    first = packet(7)
    assert decoder.feed(first[:7], 1) == []
    assert decoder.feed(first[7:10], 2) == []
    result = decoder.feed(first[10:], 3)
    assert [t for _, t in result[:3]] == [1, 2, 3]


def test_random_noise_bounded_and_reset():
    decoder = StreamDecoder(7)
    rng = random.Random(12)
    decoder.feed(bytes(rng.randrange(256) for _ in range(5000)), 1)
    assert len(decoder._bytes) <= 124
    decoder.reset()
    assert decoder.resets == 1
    assert len(decoder._bytes) == 0
    assert len(decoder.feed(packet(7), 2)) == 25
