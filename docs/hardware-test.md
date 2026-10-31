# Physical-device qualification

**Status: pending physical execution.** Software simulations are separate evidence.
Before running this procedure, obtain the accessible Linux peripheral-acquisition
host, the actual 3017LP USB unit and a compatible Nonin sensor. Record the sensor
model; do not infer that an ear clip is present or compatible from the USB model.
This procedure prepares a device bridge. It does not qualify a full multimodal
recording or prove synchronization with an ultrasound scanner.

## 1. Inventory and configuration

Photograph or transcribe the unit label, model, part number, serial number and
sensor model. Verify 3017LP USB, P/N 8982-001 and fixed Format 7 against the label
and manufacturer documentation. Inspect the sensor and connect it according to
its instructions. Run on the acquisition host, from this checkout:

```sh
mkdir -p "$HOME/nonin-qualification"
uname -a
cat /etc/os-release
id
lsusb
python -m serial.tools.list_ports -v
ls -l /dev/serial/by-id/
python --version
python -m pip freeze > "$HOME/nonin-qualification/python-packages.txt"
git rev-parse HEAD > "$HOME/nonin-qualification/commit.txt"
nonin-lsl --help
```

Save these outputs in the session report. Record the tested liblsl and
LabRecorder versions using their installed version/about interfaces. Select the
actual device path, check `ls -l` on it, and verify serial group permissions.
Use a separate Linux peripheral-acquisition computer with the intended network
connection. Stop other software using the port.

## 2. Publish and record a short XDF

In the publisher terminal, replace the path below with the verified port:

```sh
set -o pipefail
nonin-lsl --port /dev/ttyUSB0 --format 7 2>&1 | tee "$HOME/nonin-qualification/publisher.log"
```

In another terminal, inspect the actual stream XML:

```sh
python - <<'PY'
from pylsl import resolve_byprop, StreamInlet
streams = resolve_byprop('type', 'PPG', timeout=10)
for stream in streams:
    if stream.name() == 'Nonin Medical Pulse Oximeter':
        inlet = StreamInlet(stream)
        try:
            print(inlet.info(timeout=5).as_xml())
        finally:
            inlet.close_stream()
PY
LabRecorder
```

In LabRecorder, select the verified Nonin stream and save a short XDF to a new
session directory. Check the stream source ID, selected model/format, seven
channels, float32 representation and nominal 75 Hz. Keep the publisher log with
the XDF. Record wall-clock start/stop times and activity notes. Check waveform
variation and status visibility without interpreting a plausible trace as
validated timing or physiological accuracy.

Install the optional replay dependencies and inspect the file:

```sh
python -m pip install pyxdf numpy matplotlib
python tools/inspect_xdf.py /path/to/session.xdf --output-dir /path/to/new-inspection
```

The helper disables timestamp dejittering, applies XDF host-clock correction,
checks channel labels and writes `summary.json` and
`waveform-status-timing.png`. With more than one Nonin stream, pass the exact
`--source-id` printed from XML. Store the XDF, logs and generated plots outside
Git. Record replay library versions. Clock correction and resets still affect
loaded times; retain the original XDF for later inspection.

## 3. Representative session and continuity

Choose and record a duration representative of intended use; no duration is
assumed here. Repeat the recording and replay procedure. Report:

- Wall-clock session duration, receive-time span, sample count and effective
  rate. The helper uses `(sample_count - 1) / receive_span_seconds`; this is an
  interval-based summary and excludes startup/recording-boundary loss.
- Receive timestamp interval distribution, duplicate and backward intervals,
  maximum interval and intervals above a stated threshold. The helper's
  0.1-second threshold is a descriptive default, not an acceptance criterion or
  a count of lost sensor samples.
- Startup/recovery delays, discarded bytes, rejected aligned frames, decoder
  resets/acquisitions, `checksum_errors_aligned`, buffered bursts and serial errors
  from the publisher log. The checksum counter covers expected aligned frames;
  checksum failures during initial acquisition cannot be counted reliably.
  Rejected candidates are not a one-to-one count of missing samples or checksum
  failures. Preserve the exact counters and event meanings used by this version.
- Sensor-disconnect, alarm, out-of-track and artifact intervals, plus any flat,
  clipped or implausible waveform segments. Keep excluded intervals inspectable.

A rate near 75 Hz cannot rule out losses. There is no device sample counter;
whole-packet losses can be invisible to parser cadence. Sensor processing and
USB buffering can delay all receive timestamps. Report these limitations even
when all observed frames are valid.

## 4. Sensor and USB interruption

While recording, note event times and perform each step separately:

1. Remove the sensor from the measurement site, then replace it. Inspect sensor
   alarm/out-of-track and waveform behavior.
2. Disconnect the sensor cable from the Xpod, then reconnect it. Inspect sensor
   disconnect and recovery. Record which states the actual unit emits and any
   delay; do not replace observations with expected flag behavior.
3. Disconnect USB. Confirm an error in the publisher log, nonzero exit and stream
   interruption. Reconnect USB, enumerate the port again and manually restart
   `nonin-lsl --port ACTUAL_PORT --format 7`.
4. Inspect whether LabRecorder resumes receiving or needs a new selection/file.
   The application requires a manual restart; record the new outlet/recording
   boundary. Replay the relevant files and document interruption/recovery.

## 5. Reference timing, when available

Record what reference was used, how it was synchronized and how reference events
were measured. A pulse-timing comparison can assess fixed delay, jitter and drift;
its accuracy depends on the reference and measurement method. Preserve repeated
reference events across the session and include failures/unusable intervals.

For peripheral-to-fUSI alignment, first verify the scanner's actual acquisition
window timestamps and available event interface. Use repeated shared reference
events if supported; measure offset, drift and uncertainty against the required
use case. An LSL host clock relationship alone does not establish sensor-to-scanner
timing. If no suitable reference or scanner interface is available, mark these
checks unverified and list the exact missing dependency.

## Report template

- Status: pending / partially tested / tested (state which checks).
- Date/operator; unit label/model/P/N/serial; sensor model.
- Host OS, permissions, USB/serial path, software commit and dependency versions.
- Commands/configuration; XDF/log/artifact locations; wall-clock duration.
- Count, receive-time span, effective rate, interval distribution and gaps.
- Parser counters, checksum/structural rejection observations, recovery events;
  do not label an aggregate rejection counter as checksum-only errors.
- Representative waveform, quality-state and timestamp plots with units.
- Sensor removal/cable disconnect and USB reconnect observations.
- Reference, fixed delay/jitter/drift, repeated-event and scanner evidence, or
  explicit reasons these are unverified.
- Missing-data limits, unresolved problems and next checks.

Do not fill this template with synthetic test outputs as physical observations.
