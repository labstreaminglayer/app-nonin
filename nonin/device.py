from serial import Serial
from typing import Dict
from pylsl import local_clock


class Nonin:
    "Object resembling the Nonin 3012 LP USB for data handling"

    def __init__(self, port, baudrate=9600, protocol=2):
        if protocol is not 2:
            raise NotImplementedError("Only protocol 2 is supported")
        self.serial = Serial(port, baudrate)
        self.packet_count = 0
        self.frame_count = 0
        self.serial.flush()

    def read_frame(self):
        "Reads the next data packet from the device"
        frame = self.serial.read_until(b"\x01")
        while len(frame) < 5:
            frame = frame + self.serial.read_until(b"\x01")
        self.frame_count += 1
        return frame[-5:]

    def read(self) -> Dict[str, int]:
        frame = self.read_frame()
        status, pleth, other, chksum, start = frame
        status = self.parse_status(status)
        if status["Frame Sync"] == 1:
            self.packet_count += 1
            print(f"Packet #{self.packet_count:10.0f}")
            self.frame_count = 0
        pleth = self.parse_pleth(pleth)
        return {**status, **pleth}

    @staticmethod
    def parse_status(status: int) -> Dict[str, int]:
        "Returns a tuple of status flags"
        # packet starts when sync byte is 0x01
        sync = (status >> 0) & 1
        # Perfusion score
        gprf = (status >> 1) & 1
        rprf = (status >> 1) & 2
        perfscore = 0
        if rprf:
            perfscore = 1
        if gprf:
            perfscore = 3
        if rprf and gprf:
            perfscore = 2
        # print(rprf, gprf, perfscore)
        # sensor alarm
        snsa = (status >> 3) & 1
        oot = (status >> 4) & 1
        artf = (status >> 5) & 1
        snsd = (status >> 6) & 1
        # always set
        if ((status >> 7) & 1) != 1:
            print(ValueError("Status bit 7 is not set"))

        return {
            "Frame Sync": sync,
            "Perfusion Amplitude": perfscore,
            "Sensor Alarm": snsa,
            "Out Of Track": oot,
            "Artifact - short term": artf,
            "Sensor disconnect": snsd,
        }

    @staticmethod
    def parse_pleth(pleth: int) -> Dict[str, int]:
        return {"PPG": pleth}


if __name__ == "__main__":
    nonin = Nonin("/dev/ttyUSB0")
    t0 = local_clock()
    while True:
        data = nonin.read()
        td = local_clock() - t0
        if nonin.frame_count == 0:
            print(f"Fs = {1/(td / (25 * nonin.packet_count)):3.3f}Hz")