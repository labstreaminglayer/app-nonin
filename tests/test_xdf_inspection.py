"""Test receive-time summaries without treating gaps as sample-loss counts."""

import importlib.util
from pathlib import Path

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location(
    "inspect_xdf", Path(__file__).parents[1] / "tools" / "inspect_xdf.py"
)
inspection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inspection)


def test_bursts_and_gap_summary():
    samples = np.zeros((4, 7))
    samples[2:, 6] = 1
    report = inspection.summarize(samples, [1, 1, 1.02, 1.5])
    assert report["sample_count"] == 4
    assert report["effective_rate_hz"] == 6
    assert report["duplicate_receive_intervals"] == 1
    assert report["intervals_exceeding_gap_threshold"] == 1
    assert report["flagged_samples_by_channel"]["Sensor disconnect"] == 2


def test_one_sample_and_bad_clock():
    assert inspection.summarize(np.zeros((1, 7)), [3])["effective_rate_hz"] is None
    assert (
        inspection.summarize(np.zeros((2, 7)), [3, 2])["backward_receive_intervals"]
        == 1
    )
    with pytest.raises(ValueError):
        inspection.summarize(np.zeros((2, 7)), [3, float("nan")])
