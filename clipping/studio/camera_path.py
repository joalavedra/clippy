"""Shared camera-path interpolation and hard-cut refinement helpers."""

from __future__ import annotations

import cv2
import numpy as np


def fallback_intervals(
    samples: list[dict],
    cuts: list[float],
    duration: float,
    min_coverage: float = 0.3,
    min_len: float = 0.8,
) -> list[tuple[float, float]]:
    """Find shot and within-shot spans where face tracking should be bypassed."""
    if duration <= 0:
        return []

    boundaries = [0.0]
    boundaries.extend(
        sorted(
            {
                max(0.0, min(float(cut), float(duration)))
                for cut in cuts
                if 0.0 < float(cut) < float(duration)
            }
        )
    )
    boundaries.append(float(duration))
    ordered_samples = sorted(
        (
            sample
            for sample in samples
            if 0.0 <= float(sample.get("time", -1)) <= duration
        ),
        key=lambda sample: float(sample["time"]),
    )
    sample_times = [float(sample["time"]) for sample in ordered_samples]
    spacings = [
        second - first
        for first, second in zip(sample_times, sample_times[1:])
        if second > first
    ]
    step = float(np.median(spacings)) if spacings else 0.0
    miss_run_length = (
        max(4, int(np.ceil(2.0 / step))) if step > 0 else len(ordered_samples) + 1
    )
    intervals: list[tuple[float, float]] = []

    for start, end in zip(boundaries, boundaries[1:]):
        in_shot = [
            sample
            for sample in ordered_samples
            if start <= float(sample["time"]) < end
            or (
                end == duration
                and float(sample["time"]) == end
            )
        ]
        if not in_shot:
            continue
        coverage = (
            sum(bool(sample.get("detected", False)) for sample in in_shot)
            / len(in_shot)
        )
        shot_fallback = end - start >= min_len and coverage < min_coverage
        if shot_fallback:
            intervals.append((start, end))
            continue
        if step <= 0:
            continue

        run_start = None
        run_length = 0
        previous_miss_time = 0.0
        for sample in in_shot:
            if sample.get("detected", False):
                if run_start is not None and run_length >= miss_run_length:
                    intervals.append(
                        (
                            max(start, run_start),
                            min(end, float(previous_miss_time) + step),
                        )
                    )
                run_start = None
                run_length = 0
                continue
            if run_start is None:
                run_start = float(sample["time"])
            run_length += 1
            previous_miss_time = float(sample["time"])
        if run_start is not None and run_length >= miss_run_length:
            intervals.append(
                (
                    max(start, run_start),
                    min(end, float(previous_miss_time) + step),
                )
            )

    merged: list[tuple[float, float]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def in_intervals(
    intervals: list[tuple[float, float]],
    t: float,
    duration: float | None = None,
) -> bool:
    """Return whether ``t`` falls inside any fallback interval."""
    return any(
        start <= t < end
        or (duration is not None and t == end and end >= duration)
        for start, end in intervals
    )


def detect_cuts(
    cap,
    clip_start: float,
    duration: float,
    fps: float,
    threshold: float = 25.0,
) -> list[float]:
    """Detect shot cuts with one sequential pass over the clip."""
    if cap is None or duration <= 0 or fps <= 0:
        return []

    cuts: list[float] = []
    cluster_time = None
    cluster_diff = -1.0
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, clip_start * 1000)
        ret, previous_frame = cap.read()
        if not ret:
            return cuts

        previous_gray = cv2.resize(
            cv2.cvtColor(previous_frame, cv2.COLOR_BGR2GRAY),
            (64, 36),
            interpolation=cv2.INTER_AREA,
        )
        frame_index = 1
        max_frames = int(round(duration * fps)) + 1
        while frame_index <= max_frames:
            ret, frame = cap.read()
            if not ret:
                break
            gray = cv2.resize(
                cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY),
                (64, 36),
                interpolation=cv2.INTER_AREA,
            )
            diff = float(np.mean(cv2.absdiff(gray, previous_gray)))
            current_time = min(duration, frame_index / fps)
            if diff > threshold:
                if cluster_time is None or diff > cluster_diff:
                    cluster_time = current_time
                    cluster_diff = diff
            elif cluster_time is not None:
                cuts.append(cluster_time)
                cluster_time = None
                cluster_diff = -1.0
            previous_gray = gray
            frame_index += 1

        if cluster_time is not None:
            cuts.append(cluster_time)
    except Exception:
        return []
    return cuts


def _nearest_cut(cuts: list[float], sample_time: float, tolerance: float):
    if not cuts:
        return None
    cut = min(cuts, key=lambda value: abs(value - sample_time))
    return cut if abs(cut - sample_time) <= tolerance else None


def nearest_cut(cuts: list[float], sample_time: float, tolerance: float):
    """Return the nearest cut within tolerance, if one exists."""
    return _nearest_cut(cuts, sample_time, tolerance)


def is_near_cut(cuts: list[float], sample_time: float, tolerance: float) -> bool:
    """Return whether a sample is close enough to a detected shot cut."""
    return _nearest_cut(cuts, sample_time, tolerance) is not None


def cut_between(cuts: list[float], start: float, end: float):
    """Return the first detected cut in an interval, if any."""
    for cut in cuts:
        if start < cut <= end:
            return cut
    return None


def mark_snaps(samples: list[dict], snap_px: float) -> None:
    """Mark large horizontal camera jumps as hard cuts."""
    for index, sample in enumerate(samples):
        if index == 0:
            sample.setdefault("snap", False)
            continue
        previous = samples[index - 1]
        sample["snap"] = abs(
            float(sample.get("cx", 0)) - float(previous.get("cx", 0))
        ) > snap_px


def mark_cut_snaps(samples: list[dict], cuts: list[float]) -> None:
    """Mark the first camera sample at or after each source shot cut."""
    if not samples or not cuts:
        return
    for cut in cuts:
        for sample in samples[1:]:
            if float(sample["time"]) + 1e-6 >= float(cut):
                sample["snap"] = True
                break


def refine_snap_times(
    samples: list[dict],
    cuts: list[float],
    sample_step: float,
) -> None:
    """Align hard snaps to the nearest detected shot cut."""
    if not samples:
        return

    tolerance = sample_step + 0.05
    for sample in samples:
        if not sample.get("snap"):
            continue
        sample_time = float(sample["time"])
        snap_at = _nearest_cut(cuts, sample_time, tolerance)
        sample["snap_at"] = sample_time if snap_at is None else snap_at
        print(
            f"[camera] snap at {sample['snap_at']:.3f}s "
            f"(refined from {sample_time:.3f}s)",
            flush=True,
        )


class LayoutTimeline:
    """Stepwise layout decisions with cut alignment and flicker hysteresis."""

    def __init__(self, initial_layout: str):
        self.events = [{"time": 0.0, "layout": initial_layout}]

    def add(self, time: float, layout: str) -> None:
        if self.events[-1]["layout"] != layout:
            self.events.append({"time": float(time), "layout": layout})

    def lookup(self, time: float) -> str:
        layout = self.events[0]["layout"]
        for event in self.events:
            if event["time"] > time:
                break
            layout = event["layout"]
        return layout


def interp(
    samples: list[dict],
    t: float,
    keys=("cx", "cy", "zoom"),
    defaults=(0.0, 0.0, 1.0),
) -> tuple:
    """Interpolate camera samples, stepping at refined hard cuts."""
    if not samples:
        return tuple(defaults[: len(keys)])

    def values(sample: dict) -> tuple:
        return tuple(
            sample.get(key, defaults[index])
            for index, key in enumerate(keys)
        )

    if t <= samples[0]["time"]:
        return values(samples[0])
    if t >= samples[-1]["time"]:
        return values(samples[-1])

    for index in range(len(samples) - 1):
        current = samples[index]
        following = samples[index + 1]
        if current["time"] <= t <= following["time"]:
            snap_at = following.get("snap_at", following["time"])
            if following.get("snap") and t < snap_at:
                return values(current)
            if following.get("snap"):
                return values(following)

            t1, t2 = current["time"], following["time"]
            if t1 == t2:
                return values(current)
            fraction = (t - t1) / (t2 - t1)
            first = values(current)
            second = values(following)
            return tuple(
                first[item] + (second[item] - first[item]) * fraction
                for item in range(len(keys))
            )

    return values(samples[-1])
