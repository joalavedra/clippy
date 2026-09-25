import importlib.util
from pathlib import Path

import cv2
import numpy as np


def _load_studio_module(name):
    path = Path(__file__).parents[1] / "clipping" / "studio" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"test_studio_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


camera_path = _load_studio_module("camera_path")
utils = _load_studio_module("utils")
fallback_intervals = camera_path.fallback_intervals
in_intervals = camera_path.in_intervals
fit_frame_blur = utils.fit_frame_blur
fit_frame_pad = utils.fit_frame_pad


def _samples(times, detected):
    return [
        {"time": time, "detected": value}
        for time, value in zip(times, detected)
    ]


def test_fallback_intervals_cover_face_free_shot():
    samples = _samples(
        np.arange(0, 4.01, 0.5),
        [True, True, True, True, False, False, False, False, False],
    )
    assert fallback_intervals(samples, [2.0], 4.0) == [(2.0, 4.0)]


def test_fallback_intervals_keep_well_detected_shot():
    samples = _samples(
        np.arange(0, 4.01, 0.5),
        [True, True, True, True, True, True, True, True, False],
    )
    assert fallback_intervals(samples, [], 4.0) == []


def test_short_face_free_shot_is_not_fallback():
    samples = _samples(np.arange(0, 0.61, 0.2), [False, False, False, False])
    assert fallback_intervals(samples, [], 0.6) == []


def test_long_miss_run_inside_detected_shot():
    times = np.arange(0, 5.01, 0.5)
    detected = [True, True, True, False, False, False, False, True, True, True, True]
    intervals = fallback_intervals(_samples(times, detected), [], 5.0)
    assert intervals == [(1.5, 3.5)]
    assert in_intervals(intervals, 2.0)
    assert not in_intervals(intervals, 3.5)


def test_miss_run_extends_until_detection():
    times = np.arange(0, 5.01, 0.5)
    detected = [True, True, False, False, False, False, False, False, True, True, True]
    intervals = fallback_intervals(_samples(times, detected), [], 5.0)
    assert intervals == [(1.0, 4.0)]


def test_unsampled_shot_is_not_fallback():
    samples = _samples([0.0, 0.5, 1.9], [True, True, True])
    assert fallback_intervals(samples, [1.0, 1.9], 2.0) == []


def test_fallback_intervals_merge_adjacent_spans():
    samples = _samples(
        np.arange(0, 4.01, 0.5),
        [False, False, False, False, False, False, False, False, False],
    )
    assert fallback_intervals(samples, [2.0], 4.0) == [(0.0, 4.0)]
    assert in_intervals([(0.0, 4.0)], 4.0, 4.0)


def test_fit_frame_helpers_preserve_canvas_and_padding():
    frame = np.full((360, 640, 3), 255, dtype=np.uint8)
    padded = fit_frame_pad(frame, 1080, 1920)
    blurred = fit_frame_blur(frame, 1080, 1920)

    assert padded.shape == (1920, 1080, 3)
    assert blurred.shape == (1920, 1080, 3)
    assert np.all(padded[0] == 0)
    assert np.all(blurred[0] > 0)
    assert np.all(padded[960] == 255)
    assert np.all(blurred[960] == 255)

    gradient = np.zeros((360, 640, 3), dtype=np.uint8)
    gradient[:, :, 0] = np.arange(640, dtype=np.uint8)
    gradient[:, :, 1] = np.arange(360, dtype=np.uint8)[:, None]
    expected = cv2.resize(gradient, (1080, 608), interpolation=cv2.INTER_AREA)
    fitted = fit_frame_pad(gradient, 1080, 1920)
    assert np.array_equal(fitted[960], expected[304])
