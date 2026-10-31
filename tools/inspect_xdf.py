#!/usr/bin/env python3
"""Inspect Nonin XDF data without smoothing serial receive timestamps.

Requires pyxdf, numpy and matplotlib. Reported gaps are receive-time observations,
not an estimate of lost sensor samples. Preserve application logs separately.
"""

import argparse
import json
from pathlib import Path

import numpy as np

LABELS = (
    "PPG",
    "Frame Sync",
    "Perfusion Amplitude",
    "Sensor Alarm",
    "Out Of Track",
    "Artifact - short term",
    "Sensor disconnect",
)


def summarize(samples, timestamps, gap_threshold=0.1):
    """Summarize receive intervals; all times and the threshold are seconds."""
    samples = np.asarray(samples, dtype=float)
    timestamps = np.asarray(timestamps, dtype=float)
    if samples.ndim != 2 or samples.shape[1] != 7:
        raise ValueError("Expected a seven-channel Nonin stream")
    if timestamps.ndim != 1 or len(timestamps) != len(samples):
        raise ValueError("Samples and timestamps must have matching lengths")
    if not len(samples) or not np.isfinite(timestamps).all():
        raise ValueError("Need nonempty data with finite timestamps")
    if not np.isfinite(gap_threshold) or gap_threshold <= 0:
        raise ValueError("gap threshold must be positive seconds")
    intervals = np.diff(timestamps)
    span = float(timestamps[-1] - timestamps[0])
    positive = intervals[intervals > 0]
    return {
        "sample_count": len(samples),
        "receive_span_seconds": span,
        "effective_rate_hz": ((len(samples) - 1) / span if span > 0 else None),
        "interval_count": len(intervals),
        "duplicate_receive_intervals": int(np.count_nonzero(intervals == 0)),
        "backward_receive_intervals": int(np.count_nonzero(intervals < 0)),
        "gap_threshold_seconds": gap_threshold,
        "intervals_exceeding_gap_threshold": int(
            np.count_nonzero(intervals > gap_threshold)
        ),
        "maximum_receive_interval_seconds": (
            float(intervals.max()) if len(intervals) else None
        ),
        "positive_interval_percentiles_seconds": (
            dict(
                zip(("p5", "p50", "p95"), np.percentile(positive, [5, 50, 95]).tolist())
            )
            if len(positive)
            else None
        ),
        "flagged_samples_by_channel": {
            label: int(np.count_nonzero(samples[:, index]))
            for index, label in enumerate(LABELS)
            if index >= 3
        },
        "nonfinite_waveform_samples": int(
            np.count_nonzero(~np.isfinite(samples[:, 0]))
        ),
        "limitation": "Receive times, not acquisition times; gap counts do not establish sample loss. Checksum/recovery counts require app logs.",
    }


def load_stream(path, source_id=None):
    import pyxdf

    streams, _ = pyxdf.load_xdf(
        str(path), dejitter_timestamps=False, synchronize_clocks=True
    )
    candidates = [
        stream
        for stream in streams
        if stream["info"].get("type") == ["PPG"]
        and stream["info"].get("name") == ["Nonin Medical Pulse Oximeter"]
        and (source_id is None or stream["info"].get("source_id") == [source_id])
    ]
    if len(candidates) != 1:
        raise ValueError(
            "Need exactly one Nonin stream; select --source-id when multiple streams exist"
        )
    stream = candidates[0]
    channels = stream["info"]["desc"][0]["channels"][0]["channel"]
    labels = tuple(channel["label"][0] for channel in channels)
    if labels != LABELS:
        raise ValueError(f"Unexpected channel contract: {labels}")
    return stream


def plot_stream(samples, timestamps, output):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    samples, timestamps = np.asarray(samples), np.asarray(timestamps)
    elapsed = timestamps - timestamps[0]
    figure, axes = plt.subplots(
        4, 1, figsize=(12, 9), sharex=True, constrained_layout=True
    )
    axes[0].plot(elapsed, samples[:, 0], linewidth=0.8)
    axes[0].set_ylabel("PPG (arbitrary units)")
    axes[0].set_title("Nonin waveform and status against recorded receive time")
    for index in range(3, 7):
        axes[1].step(
            elapsed, samples[:, index], where="post", label=LABELS[index], alpha=0.8
        )
    axes[1].set_ylabel("Status flag (0/1)")
    axes[1].legend(loc="upper left", ncol=2, fontsize=9)
    axes[1].set_ylim(-0.1, 1.5)
    axes[2].step(elapsed, samples[:, 2], where="post")
    axes[2].set_yticks([0, 1, 2, 3], ["none", "poor", "marginal", "high"])
    axes[2].set_ylabel("Perfusion category")
    axes[3].plot(elapsed[1:], np.diff(timestamps), ".", markersize=3)
    axes[3].set_ylabel("Receive interval (s)")
    axes[3].set_xlabel("Receive time since first recorded sample (s)")
    for axis in axes:
        axis.grid(alpha=0.2)
    figure.savefig(output, dpi=150)
    plt.close(figure)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xdf", type=Path)
    parser.add_argument("--source-id")
    parser.add_argument(
        "--output-dir", type=Path, required=True, help="new directory for JSON and plot"
    )
    parser.add_argument(
        "--gap-threshold",
        type=float,
        default=0.1,
        help="receive interval threshold in seconds (default: 0.1; not a loss criterion)",
    )
    args = parser.parse_args(argv)
    stream = load_stream(args.xdf, args.source_id)
    samples, timestamps = stream["time_series"], stream["time_stamps"]
    summary = summarize(samples, timestamps, args.gap_threshold)
    summary["source_id"] = stream["info"]["source_id"][0]
    summary["xdf"] = str(args.xdf)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    plot_stream(samples, timestamps, args.output_dir / "waveform-status-timing.png")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
