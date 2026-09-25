"""Styled Story scene rendering with face tracking and ASS captions."""

import os
import shutil
import subprocess

import cv2

from .. import studio
from . import assembler, loader


def _source_dimensions(source_path: str) -> tuple[int, int]:
    cap = cv2.VideoCapture(source_path)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    if width <= 0 or height <= 0:
        raise RuntimeError(f"Could not probe source dimensions: {source_path}")
    return width, height


def _trim_video_only(
    source_path: str,
    start: float,
    end: float,
    output_path: str,
) -> None:
    duration = max(0.0, end - start)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        source_path,
        "-t",
        f"{duration:.3f}",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-avoid_negative_ts",
        "make_zero",
        output_path,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)


def render_scene_styled(
    source_path: str,
    segmen: list[dict],
    start: float,
    end: float,
    ratio: str,
    cfg,
    video_encoder,
    out_ts: str,
    label: str,
) -> str:
    """Render one Story scene with styled video and karaoke captions."""
    os.makedirs(os.path.dirname(os.path.abspath(out_ts)), exist_ok=True)
    temp_dir = out_ts + "_styled_tmp"
    os.makedirs(temp_dir, exist_ok=True)
    silent_mp4 = os.path.join(temp_dir, "silent.mp4")
    trimmed_mp4 = os.path.join(temp_dir, "trimmed.mp4")
    ass_path = os.path.join(temp_dir, "captions.ass")

    source_dim = _source_dimensions(source_path)
    target_w, target_h = studio._get_render_dims(
        cfg, ratio, source_h=source_dim[1]
    )
    get_x = None

    try:
        if studio._is_vertical_ratio(ratio):
            get_x = studio.buat_video_hybrid(
                source_path,
                silent_mp4,
                start,
                end,
                ratio,
                cfg,
                None,
                label=label,
            )
        else:
            _trim_video_only(source_path, start, end, trimmed_mp4)
            assembler._normalize_scene_segment(
                trimmed_mp4,
                silent_mp4,
                target_w,
                target_h,
            )

        has_subtitles = not getattr(cfg, "no_subs", False)
        if has_subtitles:
            studio.buat_file_ass(
                segmen,
                start,
                end,
                ass_path,
                ratio,
                cfg,
                typography_plan=[],
                gunakan_advanced=False,
                get_x_func=get_x,
                source_dim=source_dim,
            )

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            silent_mp4,
            "-ss",
            f"{start:.3f}",
            "-to",
            f"{end:.3f}",
            "-i",
            source_path,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
        ]
        if has_subtitles:
            ass_filter = studio.escape_ffmpeg_filter_value(os.path.abspath(ass_path))
            fonts_dir = studio.escape_ffmpeg_filter_value(
                os.path.abspath(cfg.font_dir)
            )
            cmd += ["-vf", f"subtitles={ass_filter}:fontsdir={fonts_dir}"]
        cmd += studio.get_ts_encode_args(video_encoder, fps=30)
        progress_cmd = studio.build_ffmpeg_progress_cmd(cmd, out_ts)
        return_code, errors = studio.run_ffmpeg_with_progress(
            progress_cmd,
            end - start,
            label=label,
        )
        if return_code != 0:
            raise RuntimeError(
                f"Styled scene render failed ({label}): {'; '.join(errors[-5:])}"
            )
        return out_ts
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _concat_ts_to_mp4(ts_parts: list[str], output_path: str) -> str:
    if not ts_parts:
        raise ValueError("No rendered scenes to concatenate.")
    concat_input = "concat:" + "|".join(os.path.abspath(path) for path in ts_parts)
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        concat_input,
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        output_path,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
    return output_path


def _remux_mp4_to_ts(input_path: str, output_path: str) -> str:
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            input_path,
            "-c",
            "copy",
            "-f",
            "mpegts",
            output_path,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    return output_path


def render_clip_styled(
    clip_config: dict,
    source_registry: dict[str, dict],
    cache_dir: str,
    transcripts: dict[str, dict],
    ratio: str,
    cfg,
    video_encoder,
    output_dir: str,
) -> dict:
    """Render a full styled Story clip and its hook/highlight variants."""
    cid = clip_config["clip_id"]
    clip_dir = os.path.abspath(output_dir)
    temp_dir = os.path.join(clip_dir, f"_styled_temp_{cid}")
    os.makedirs(temp_dir, exist_ok=True)

    hook_parts = []
    highlight_parts = []
    try:
        for section_name, destination in (
            ("hook", hook_parts),
            ("highlight", highlight_parts),
        ):
            scenes = clip_config.get(section_name, {}).get("scenes", [])
            for idx, scene in enumerate(scenes):
                source_id = scene["source_id"]
                source_path = loader.resolve_scene_path(
                    scene, source_registry, cache_dir
                )
                transcript = transcripts.get(source_id, {})
                scene_ts = os.path.join(
                    temp_dir, f"{section_name}_{idx}.ts"
                )
                render_scene_styled(
                    source_path=source_path,
                    segmen=transcript.get("segmen", []),
                    start=float(scene["start"]),
                    end=float(scene["end"]),
                    ratio=ratio,
                    cfg=cfg,
                    video_encoder=video_encoder,
                    out_ts=scene_ts,
                    label=f"Clip {cid} {section_name} {idx} {source_id}",
                )
                destination.append(scene_ts)

        if not hook_parts or not highlight_parts:
            raise RuntimeError(f"Clip {cid} has no renderable hook/highlight scenes.")

        hook_path = os.path.join(clip_dir, f"hook_{cid}.mp4")
        highlight_path = os.path.join(clip_dir, f"highlight_{cid}.mp4")
        final_path = os.path.join(clip_dir, f"clip_{cid}_final.mp4")
        hook_parts_for_final = list(hook_parts)

        hook = clip_config.get("hook", {})
        if hook.get("type") == "text_overlay" and hook.get("text"):
            hook_concat = os.path.join(temp_dir, "hook_concat.mp4")
            _concat_ts_to_mp4(hook_parts, hook_concat)
            hook_overlay = os.path.join(temp_dir, "hook_overlay.mp4")
            assembler._add_text_overlay(
                hook_concat,
                hook["text"],
                hook_overlay,
            )
            hook_parts_for_final = [
                _remux_mp4_to_ts(
                    hook_overlay,
                    os.path.join(temp_dir, "hook_overlay.ts"),
                )
            ]

        _concat_ts_to_mp4(hook_parts_for_final, hook_path)
        _concat_ts_to_mp4(highlight_parts, highlight_path)
        _concat_ts_to_mp4(hook_parts_for_final + highlight_parts, final_path)
        return {
            "hook_path": hook_path,
            "highlight_path": highlight_path,
            "final_path": final_path,
        }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
