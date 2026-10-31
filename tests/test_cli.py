from types import SimpleNamespace

from nonin import __main__ as cli


def test_format_selection_and_exit_on_worker_fault(monkeypatch):
    calls = []
    worker = SimpleNamespace(is_alive=lambda: False, error=ConnectionError("lost"))
    monkeypatch.setattr(
        cli, "run", lambda port, protocol: calls.append((port, protocol)) or worker
    )
    assert cli.main(["--port", "/dev/ttyUSB2", "--format", "7"]) == 1
    assert calls == [("/dev/ttyUSB2", 7)]
    worker.error = None
    assert cli.main([]) == 0
    assert calls[-1] == (None, 2)


def test_interrupt_closes_and_joins(monkeypatch):
    class Worker:
        error = None
        joined = 0
        stopped = False

        def is_alive(self):
            return True

        def join(self, timeout=None):
            self.joined += 1
            if self.joined == 1:
                raise KeyboardInterrupt

        def stop(self):
            self.stopped = True

    worker = Worker()
    monkeypatch.setattr(cli, "run", lambda *_: worker)
    assert cli.main([]) == 0
    assert worker.stopped and worker.joined == 2


def test_open_and_scan_errors_are_nonzero(monkeypatch):
    def fail(*args):
        raise ConnectionError("unavailable")

    monkeypatch.setattr(cli, "run", fail)
    monkeypatch.setattr(cli, "detect_nonin_devices", fail)
    assert cli.main([]) == 1
    assert cli.main(["--scan"]) == 1
