# App-Nonin

Stream the continuous pulse waveform and status from a Nonin Xpod over Lab
Streaming Layer (LSL). Format 2 remains the default for the 3012LP USB.
Select Format 7 explicitly for the standard 3017LP USB (P/N 8982-001).
A compatible Nonin sensor is required. The format option selects a decoder;
it does not reprogram the USB device or verify the label on the unit.

## Install and select a port

Use Python 3 in a virtual environment. From this checkout:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
nonin-lsl --scan
python -m serial.tools.list_ports -v
```

The scan reports USB VID/PID candidates, which may include other FTDI devices.
These identifiers do not distinguish Xpod models. Check the device label and
choose its port explicitly; a stable Linux `/dev/serial/by-id/…` path is useful.
If auto-discovery does not recognize the adapter, use `--port`.

On Linux, inspect `ls -l /dev/ttyUSB0` and `id`. The acquisition user needs read
and write access to the device, commonly through the `dialout` group. Where
that is the host's configured serial-access group, an administrator can run
`sudo usermod -aG dialout "$USER"`; log out and back in afterward. Group names
vary by distribution. Avoid running the recorder as root. Ensure ModemManager
or another application is not opening the same port.

## Run

```sh
# Existing 3012LP / Format 2 usage:
nonin-lsl --port /dev/ttyUSB0

# Standard 3017LP USB, fixed Format 7:
nonin-lsl --port /dev/ttyUSB0 --format 7
```

Both use 9600 baud, eight data bits, no parity, one stop bit and no flow control.
Stop with Ctrl-C. USB disconnects stop the publisher with an error; reconnect
the device, check its port, and restart the command. The application does not
automatically reconnect. Check the new outlet in LabRecorder and start a new
recording when needed; outlet recreation and stable source IDs do not guarantee
that an existing recorder will recover.

## Stream contract

The stream name is `Nonin Medical Pulse Oximeter`, type `PPG`, nominal rate
75 samples/s, with seven `float32` channels in this order:

| Channel | Meaning |
| --- | --- |
| PPG | Format 2: compressed 8-bit value, 0–255. Format 7: original 16-bit value, 0–65535. Arbitrary units; no scaling to 0–255. |
| Frame Sync | 1 at the first frame of each 25-frame packet; otherwise 0. |
| Perfusion Amplitude | 0: no pulse indication; 1: red/poor; 2: yellow/marginal; 3: green/high. This is a categorical indicator, not a measured physical amplitude. |
| Sensor Alarm | Unusable signal, including sensor removal from the measurement site. |
| Out Of Track | Absence of consecutive good pulses. |
| Artifact - short term | Device artifact indication during a pulse. |
| Sensor disconnect | Sensor disconnected or inoperable. |

Status channels contain integers (flags are 0/1) stored as float32. Every integer
in either waveform range is exactly representable in float32. Channel labels,
order, numeric type and nominal rate are retained for Format 2. Check status
alongside PPG: a checksum-valid frame can still contain an unusable measurement.
Invalid protocol frames are rejected rather than replaced with zeros or repeated
valid samples. The stream does not include SpO2 or pulse-rate numerics from the
multiplexed auxiliary byte.

Format 2 retains source ID `Nonin_3012_LP_USB_<serial>_<hostname>`; Format 7 uses
`Nonin_3017_LP_USB_<serial>_<hostname>`. Metadata identifies the selected model,
format, raw waveform representation, and timing policy. Selection is operator
configuration, not hardware identification. Record the label and sensor model
separately. Missing USB serial numbers can make identifiers ambiguous; avoid
running multiple otherwise identical outlets on one host.

## Timing, buffering and data quality

Timestamps are seconds on the publishing host's LSL clock, captured when the
serial read completing each frame returns. They are **receive times**, not sensor
acquisition times. Frames completed in one buffered read can share a timestamp.
The parser retains their receive timestamps while validating packet alignment;
publication time can therefore be later than the sample timestamp. No nominal
75 Hz backdating, interpolation or replacement samples are applied.

Startup and recovery require a complete, checksum-valid 25-frame packet with
consistent frame-sync positions. This adds up to about two packet periods
(roughly 0.67 s at the nominal rate) before publication from an arbitrary start;
ongoing corrupt input can take longer. Partial startup/recovery data may be
discarded. Once synchronized, validated frames are published individually.

Logs expose rejected candidates, discarded bytes, synchronization/recovery,
stalls, buffered reads and disconnects. Shutdown logs include delivered frame and
packet totals, discarded bytes, rejected aligned frames, checksum failures on
aligned frames (`checksum_errors_aligned`), resets and acquisitions. Checksum
failures before alignment are included only in discarded-byte accounting. Counters describe observable parser
behavior, not the exact number of lost sensor samples. The protocol has no
sample sequence counter: loss of a whole 25-frame packet, or some combinations
of corruption, cannot always be detected. A nominal 75 Hz declaration or a
plausible effective rate is not proof of continuity.

LSL clock correction aligns host clocks. It does not remove sensor processing,
USB/serial buffering or acquisition delay, nor measure sensor-to-scanner offset,
jitter or drift. XDF replay tools may smooth timestamps for regular streams;
inspect with dejittering disabled when assessing buffering and gaps.

## Troubleshooting

- **No device:** check power, USB connection, label/model and port enumeration.
  Try an explicit port; the candidate USB identifiers are not model detection.
- **Permission denied / busy:** check group membership and exclusive port use.
- **No samples or repeated rejections:** confirm `--format` matches the fixed
  format of the USB unit. A wrong decoder must not be treated as valid PPG.
  Check serial settings and logs; allow startup synchronization time.
- **Flat or implausible waveform:** inspect all quality flags, sensor connection
  and placement. Do not diagnose sensor problems from the waveform alone.
- **USB disconnect:** restart manually after reconnecting. Preserve the logs and
  note the recording boundary. Sensor unplugging may produce flagged samples;
  USB unplugging interrupts the stream itself.
- **LSL not visible:** check host networking, firewall and liblsl availability.
  Test discovery on the sender first; serial input and LSL discovery are
  separate failure points.

## Verification and physical testing

```sh
python -m pip install -r requirements-dev.txt
# /tmp avoids SQLite coverage locks on network filesystems.
COVERAGE_FILE=/tmp/nonin-tests.coverage python -m pytest
make test PYTHON=python TEST_ENV=/tmp/nonin-wheel-test
```

Tests use synthetic protocol frames and mocked or emulated serial input. They
cover both formats, waveform preservation, status, corruption/recovery,
timeouts/disconnects, stream metadata and lifecycle behavior. They do not
establish compatibility, continuity or timing on a physical device.

[Hardware procedure](docs/hardware-test.md) contains the device inventory,
LabRecorder/XDF commands, reconnect checks and report template. Physical testing
is pending until the device, compatible sensor and acquisition host are
accessible. Record actual results there; do not label simulated tests as device
tests. [XDF inspection helper](tools/inspect_xdf.py) plots waveform, status and
receive timestamp intervals without timestamp dejittering.

## Protocol and contribution notes

The [Nonin specification](https://www.nonin.com/wp-content/uploads/2018/09/Xpod-Operators-Manual.pdf),
printed pages 9–16, defines the two formats. Each frame is five bytes; 25 frames
form a packet. Format 2 has a leading `0x01` followed by status, an 8-bit PPG
value, auxiliary data and checksum. Format 7 has status, waveform MSB, waveform
LSB, auxiliary data and checksum. The checksum is the sum of the first four
bytes modulo 256. Reserved auxiliary values are not restricted to seven bits.

[Systole's Oximeter](https://www.the-ecg.org/systole/_modules/systole/recording.html)
is a useful reference but scales Format 7 to 0–255; this application preserves
the original values. Implementation is based on the documented protocol rather
than copied reference code.

Upstream package metadata declares MIT and retains the original author credit
in `setup.py`; this baseline contains no standalone license or contribution
policy. Follow any policies added by upstream before contributing. Run the
checks above and describe physical tests separately from simulations.
