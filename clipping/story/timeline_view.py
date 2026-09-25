"""Cut-sheet timelines for inspecting Story render boundaries."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def _extract_frame(video_path: str, timestamp: float, out_path: str) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{max(0.0, timestamp):.3f}",
            "-i",
            video_path,
            "-frames:v",
            "1",
            "-q:v",
            "4",
            out_path,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _audio_envelope(
    video_path: str,
    start: float,
    end: float,
    width: int,
) -> np.ndarray:
    duration = max(0.0, end - start)
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{max(0.0, start):.3f}",
            "-i",
            video_path,
            "-t",
            f"{duration:.3f}",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "s16le",
            "-",
        ],
        check=False,
        capture_output=True,
    )
    pcm = np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32)
    if result.returncode == 0 and pcm.size:
        values = np.abs(pcm / 32768.0)
        buckets = np.array_split(values, max(1, width))
        return np.asarray(
            [float(bucket.mean()) if bucket.size else 0.0 for bucket in buckets]
        )
    return np.zeros(max(1, width), dtype=np.float32)


def _word_time(word: dict, key: str) -> float | None:
    try:
        value = word.get(key)
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _words_in_window(words: list[dict], start: float, end: float) -> list[dict]:
    result = []
    for word in words:
        word_start = _word_time(word, "start")
        word_end = _word_time(word, "end")
        if word_start is None or word_end is None:
            continue
        if word_end <= start or word_start >= end:
            continue
        result.append(word)
    return sorted(result, key=lambda item: float(item["start"]))


def render_timeline(
    video_path: str,
    start: float,
    end: float,
    words: list[dict],
    out_png: str,
    n_frames: int = 8,
    silence_gap: float = 0.4,
    markers: list[float] | None = None,
) -> str:
    """Render a filmstrip, waveform, transcript labels, and cut markers."""
    if end <= start:
        raise ValueError("Timeline end must be greater than start.")
    out_path = Path(out_png)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frame_count = max(1, n_frames)
    frame_times = (
        [(start + end) / 2.0]
        if frame_count == 1
        else [
            start + (end - start) * index / (frame_count - 1)
            for index in range(frame_count)
        ]
    )

    with tempfile.TemporaryDirectory(prefix="clippy-timeline-") as temp_dir:
        frame_paths = []
        for index, timestamp in enumerate(frame_times):
            frame_path = os.path.join(temp_dir, f"frame_{index:03d}.jpg")
            _extract_frame(video_path, timestamp, frame_path)
            frame_paths.append(frame_path)

        frame_height = 180
        margin = 32
        frame_gap = 4
        images = []
        for frame_path in frame_paths:
            image = Image.open(frame_path).convert("RGB")
            width = max(1, round(image.width * frame_height / image.height))
            images.append(image.resize((width, frame_height), Image.Resampling.LANCZOS))
        strip_width = sum(image.width for image in images) + frame_gap * (len(images) - 1)
        width = max(1280, strip_width + margin * 2)
        waveform_height = 190
        label_height = 72
        height = margin + frame_height + 18 + waveform_height + label_height + margin
        canvas = Image.new("RGB", (width, height), (21, 23, 28))
        draw = ImageDraw.Draw(canvas, "RGBA")
        font = ImageFont.load_default()
        small_font = ImageFont.load_default()

        draw.text(
            (margin, 10),
            f"{Path(video_path).name}  {start:.2f}s - {end:.2f}s",
            fill=(235, 235, 235),
            font=font,
        )
        cursor = margin
        strip_y = margin
        for image in images:
            canvas.paste(image, (cursor, strip_y))
            cursor += image.width + frame_gap

        wave_x0 = margin
        wave_x1 = width - margin
        wave_y0 = strip_y + frame_height + 18
        wave_y1 = wave_y0 + waveform_height
        draw.rectangle((wave_x0, wave_y0, wave_x1, wave_y1), fill=(30, 32, 39))

        def time_to_x(timestamp: float) -> int:
            fraction = (timestamp - start) / max(1e-6, end - start)
            return round(wave_x0 + fraction * (wave_x1 - wave_x0))

        visible_words = _words_in_window(words, start, end)
        for previous, current in zip(visible_words, visible_words[1:]):
            previous_end = _word_time(previous, "end")
            current_start = _word_time(current, "start")
            if (
                previous_end is not None
                and current_start is not None
                and current_start - previous_end > silence_gap
            ):
                draw.rectangle(
                    (
                        time_to_x(previous_end),
                        wave_y0,
                        time_to_x(current_start),
                        wave_y1,
                    ),
                    fill=(62, 75, 105, 150),
                )

        envelope = _audio_envelope(video_path, start, end, wave_x1 - wave_x0)
        midpoint = (wave_y0 + wave_y1) // 2
        amplitude = waveform_height // 2 - 10
        points_top = []
        points_bottom = []
        for index, value in enumerate(envelope):
            x = wave_x0 + round(index * (wave_x1 - wave_x0) / max(1, len(envelope) - 1))
            height_value = round(float(value) * amplitude)
            points_top.append((x, midpoint - height_value))
            points_bottom.append((x, midpoint + height_value))
        if points_top:
            draw.polygon(points_top + list(reversed(points_bottom)), fill=(107, 171, 255, 90))
            draw.line(points_top, fill=(150, 200, 255), width=1)
            draw.line(points_bottom, fill=(150, 200, 255), width=1)

        occupied_until = wave_x0 - 40
        for word in visible_words:
            word_start = _word_time(word, "start")
            word_end = _word_time(word, "end")
            label = str(word.get("word", "")).strip()
            if word_start is None or word_end is None or not label:
                continue
            x = time_to_x(word_start)
            if x - occupied_until < 42:
                continue
            draw.text((x, wave_y1 + 8), label[:18], fill=(225, 225, 230), font=small_font)
            draw.text((x, wave_y1 + 28), f"{word_start:.2f}", fill=(135, 140, 150), font=small_font)
            occupied_until = x + max(24, len(label) * 6)

        for marker in markers or []:
            if start <= marker <= end:
                x = time_to_x(marker)
                draw.line((x, strip_y, x, wave_y1), fill=(240, 70, 70), width=3)
                draw.text((x + 4, strip_y + 4), f"{marker:.2f}", fill=(255, 110, 110), font=font)

        canvas.save(out_path)
    return str(out_path)


def map_words_to_output(
    scenes: list[dict],
    transcripts: dict[str, dict],
) -> list[dict]:
    """Map source transcript words into the final clip output timeline."""
    mapped = []
    fallback_offset = 0.0
    for scene in scenes:
        source_id = scene.get("source_id")
        scene_start = float(scene["start"])
        scene_end = float(scene["end"])
        offset = float(scene.get("offset", fallback_offset))
        transcript = transcripts.get(source_id, {})
        for segment in transcript.get("segmen", []):
            for word in segment.get("words", []):
                word_start = _word_time(word, "start")
                word_end = _word_time(word, "end")
                if (
                    word_start is None
                    or word_end is None
                    or word_end <= scene_start
                    or word_start >= scene_end
                ):
                    continue
                mapped_word = dict(word)
                mapped_word["start"] = max(
                    offset, offset + word_start - scene_start
                )
                mapped_word["end"] = min(
                    offset + scene_end - scene_start,
                    offset + word_end - scene_start,
                )
                mapped.append(mapped_word)
        fallback_offset = offset + scene_end - scene_start
    return sorted(mapped, key=lambda word: (word["start"], word["end"]))


def build_cut_sheet(
    final_path: str,
    scenes_in_output_time: list[dict],
    transcripts: dict[str, dict],
    out_png: str,
    window: float = 1.5,
) -> str:
    """Build one vertically stacked timeline around each internal scene cut."""
    normalized_scenes = []
    fallback_offset = 0.0
    for scene in scenes_in_output_time:
        normalized = dict(scene)
        normalized["offset"] = float(scene.get("offset", fallback_offset))
        normalized_scenes.append(normalized)
        fallback_offset = normalized["offset"] + float(scene["end"]) - float(scene["start"])

    mapped_words = map_words_to_output(normalized_scenes, transcripts)
    boundaries = [
        normalized_scenes[index]["offset"]
        for index in range(1, len(normalized_scenes))
    ]
    if not boundaries:
        boundaries = [0.0]

    with tempfile.TemporaryDirectory(prefix="clippy-cut-sheet-") as temp_dir:
        sheets = []
        for index, boundary in enumerate(boundaries):
            start = max(0.0, boundary - window)
            end = boundary + window
            sheet_path = os.path.join(temp_dir, f"sheet_{index:03d}.png")
            render_timeline(
                final_path,
                start,
                end,
                mapped_words,
                sheet_path,
                markers=[boundary],
            )
            sheets.append(Image.open(sheet_path).convert("RGB"))
        width = max(image.width for image in sheets)
        height = sum(image.height for image in sheets) + 16 * (len(sheets) - 1)
        canvas = Image.new("RGB", (width, height), (21, 23, 28))
        y = 0
        for image in sheets:
            canvas.paste(image, (0, y))
            y += image.height + 16
        Path(out_png).parent.mkdir(parents=True, exist_ok=True)
        canvas.save(out_png)
    return str(out_png)
