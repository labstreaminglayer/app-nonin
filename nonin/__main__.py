import argparse
import logging

from nonin.device import detect_nonin_devices, Nonin
from nonin.outlet import Outlet


def scan():
    print("Searching for Nonin Medical Pulse Oximeters")
    for device in detect_nonin_devices():
        print(device.device)


def run(port=None, protocol=2) -> Outlet:
    """Start an LSL outlet using the selected serial port and data format."""
    nonin = Nonin(port=port, protocol=protocol)
    outlet = Outlet(nonin)
    try:
        outlet.start()
    except Exception:
        nonin.close()
        raise
    return outlet


def main(argv=None):
    parser = argparse.ArgumentParser(description="Stream a Nonin pulse oximeter to LSL")
    parser.add_argument("--scan", action="store_true", help="report the available devices")
    parser.add_argument("--port", default=None, help="which port to use")
    parser.add_argument("--format", type=int, choices=(2, 7), default=2, help="device data format (default: 2)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        if args.scan:
            scan()
            return 0
        outlet = run(args.port, args.format)
        try:
            while outlet.is_alive():
                outlet.join(timeout=0.5)
        except KeyboardInterrupt:
            try:
                outlet.stop()
            finally:
                outlet.join()
        return 1 if outlet.error else 0
    except Exception as exc:
        logging.error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
