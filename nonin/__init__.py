from nonin.device import Nonin


def run(port=None, protocol=2):
    """Start a Nonin LSL outlet (lazy import preserves ``python -m nonin``)."""
    from nonin.__main__ import run as start

    return start(port=port, protocol=protocol)
