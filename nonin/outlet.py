"""Publish validated Nonin samples to Lab Streaming Layer."""
import logging
import threading
import time
from socket import gethostname

from pylsl import StreamInfo, StreamOutlet


logger = logging.getLogger(__name__)
CHANNELS = (
    "PPG", "Frame Sync", "Perfusion Amplitude", "Sensor Alarm", "Out Of Track",
    "Artifact - short term", "Sensor disconnect",
)


def create_stream_outlet(nonin):
    info = StreamInfo(
        name="Nonin Medical Pulse Oximeter", type="PPG", channel_count=7,
        nominal_srate=75, channel_format="float32",
        source_id=f"Nonin_{nonin.model[:4]}_LP_USB_{nonin.serial_number}_{gethostname()}",
    )
    desc = info.desc()
    desc.append_child_value("selected_model", nonin.model)
    desc.append_child_value("data_format", str(nonin.protocol))
    desc.append_child_value("model_identity", "Selected configuration; not detected hardware identity")
    desc.append_child_value("sample_representation", "Raw unsigned 16-bit PPG" if nonin.protocol == 7 else "Raw unsigned 8-bit PPG")
    desc.append_child_value("timestamp_policy", "Host LSL clock at completion of serial read; buffered frames may share a timestamp; not sensor acquisition time")
    desc.append_child_value("quality_flags", "Status flags report device sensor and signal conditions")
    desc.append_child_value("sequence_counter", "None; sample loss cannot be fully detected")
    channels = desc.append_child("channels")
    for index, name in enumerate(CHANNELS):
        channels.append_child("channel").append_child_value("label", name).append_child_value(
            "unit", "au"
        ).append_child_value("type", "PPG" if index == 0 else "STATE")
    logger.info("Creating LSL stream: %s", info.as_xml())
    return StreamOutlet(info, chunk_size=0, max_buffered=1)


class Outlet(threading.Thread):
    """Publish until stopped or a device/LSL error occurs; inspect ``error`` after joining."""

    def __init__(self, nonin):
        super().__init__()
        self.nonin = nonin
        self.error = None
        self._stop_requested = threading.Event()

    def stop(self):
        self._stop_requested.set()
        self.nonin.close()

    def run(self):
        last_timeout_log = 0.0
        try:
            stream = create_stream_outlet(self.nonin)
            while not self._stop_requested.is_set():
                try:
                    data = self.nonin.read()
                except TimeoutError:
                    now = time.monotonic()
                    if now - last_timeout_log >= 10:
                        logger.warning("No valid samples received; packets=%s frames=%s", self.nonin.packet_count, self.nonin.frame_count)
                        last_timeout_log = now
                    continue
                stream.push_sample([data[name] for name in CHANNELS], timestamp=self.nonin.last_timestamp)
                if data["Frame Sync"]:
                    logger.info("Packets=%s frames=%s PPG=%s", self.nonin.packet_count, self.nonin.frame_count, data["PPG"])
        except Exception as exc:
            if not self._stop_requested.is_set():
                self.error = exc
                logger.exception("Outlet stopped after an error; restart manually after reconnecting the device")
        finally:
            try:
                self.nonin.close()
            except Exception as exc:
                if self.error is None:
                    self.error = exc
                logger.exception("Failed to close the device")
