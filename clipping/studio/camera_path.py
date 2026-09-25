"""Shared camera-path interpolation and hard-cut refinement helpers."""

from __future__ import annotations

import cv2
import numpy as np


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


def refine_snap_times(
    samples: list[dict],
    cap,
    clip_start: float,
    fps: float,
) -> None:
    """Refine hard-cut times using frame-to-frame visual differences."""
    if not samples or cap is None or not fps:
        return

    try:
        original_position = cap.get(cv2.CAP_PROP_POS_FRAMES)
        for index, sample in enumerate(samples):
            if index == 0 or not sample.get("snap"):
                continue

            previous_time = float(samples[index - 1]["time"])
            sample_time = float(sample["time"])
            step = 1.0 / fps
            scan_start = previous_time
            scan_time = previous_time
            cap.set(cv2.CAP_PROP_POS_MSEC, (clip_start + scan_time) * 1000)
            ret, previous_frame = cap.read()
            if not ret:
                sample["snap_at"] = sample_time
                continue

            previous_gray = cv2.resize(
                cv2.cvtColor(previous_frame, cv2.COLOR_BGR2GRAY),
                (64, 36),
                interpolation=cv2.INTER_AREA,
            )
            best_diff = -1.0
            best_time = sample_time
            scan_time = scan_start + step
            while scan_time <= sample_time + 1e-6:
                cap.set(cv2.CAP_PROP_POS_MSEC, (clip_start + scan_time) * 1000)
                ret, frame = cap.read()
                if not ret:
                    scan_time += step
                    continue
                gray = cv2.resize(
                    cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY),
                    (64, 36),
                    interpolation=cv2.INTER_AREA,
                )
                diff = float(np.mean(cv2.absdiff(gray, previous_gray)))
                if diff > best_diff:
                    best_diff = diff
                    best_time = scan_time
                previous_gray = gray
                scan_time += step

            sample["snap_at"] = (
                best_time if best_diff > 25.0 else sample_time
            )
            print(
                f"[camera] snap at {sample['snap_at']:.3f}s "
                f"(refined from {sample_time:.3f}s)",
                flush=True,
            )
        cap.set(cv2.CAP_PROP_POS_FRAMES, original_position)
    except Exception:
        for sample in samples:
            if sample.get("snap"):
                sample["snap_at"] = float(sample["time"])


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
