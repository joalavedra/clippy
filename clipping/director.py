"""Brief-driven Story recipe generation with Gemini."""

import json
import os
import subprocess
import time

from . import engine, story_runner
from .director_prompt import RECIPE_SCHEMA, build_director_prompt
from .story import loader, source_manager


def _load_transcript_bundle(
    sources: dict[str, dict],
    cache_dir: str,
    cfg,
) -> tuple[dict[str, dict], dict[str, str]]:
    """Cache sources, transcribe them, and attach their media paths."""
    os.makedirs(cache_dir, exist_ok=True)
    cache_dir, cached_paths = story_runner._prepare_source_cache(
        sources, cfg, cache_dir
    )
    transcript_meta = story_runner._transcribe_sources(
        cached_paths, cache_dir, cfg
    )

    for sid, metadata in transcript_meta.items():
        metadata["video_path"] = cached_paths.get(sid)

    transcripts = {
        sid: metadata.get("transkrip", "")
        for sid, metadata in transcript_meta.items()
        if metadata.get("transkrip")
    }
    return transcript_meta, transcripts


def load_transcripts(
    sources: dict,
    cache_dir,
    cfg,
) -> dict[str, str]:
    """Cache and transcribe sources, returning plain transcript text."""
    _, transcripts = _load_transcript_bundle(sources, cache_dir, cfg)
    return transcripts


def generate_recipe(
    transcripts,
    brief,
    ratio,
    min_duration,
    max_duration,
    num_clips,
    cfg,
    project_name,
) -> dict:
    """Ask Gemini for a Story recipe matching the director schema."""
    import google.genai as genai
    from google.genai import types

    prompt = build_director_prompt(
        transcripts=transcripts,
        brief=brief,
        ratio=ratio,
        min_duration=min_duration,
        max_duration=max_duration,
        num_clips=num_clips,
    )
    client = genai.Client(
        api_key=cfg.api_key_gemini,
        http_options=types.HttpOptions(
            timeout=engine.REQUEST_TIMEOUT_MS,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    gemini_config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=RECIPE_SCHEMA,
    )
    raw_response = engine._generate_json_with_retry(
        client=client,
        model=cfg.gemini_model,
        fallback_model=getattr(cfg, "gemini_fallback_model", None),
        contents=prompt,
        config=gemini_config,
    )

    response_path = os.path.join(cfg.outputs_dir, "director_response.json")
    os.makedirs(os.path.dirname(response_path), exist_ok=True)
    with open(response_path, "w", encoding="utf-8") as f:
        json.dump(raw_response, f, ensure_ascii=False, indent=2)
    print(f"💾 Raw director response disimpan ke: {response_path}")

    if not isinstance(raw_response, dict) or not isinstance(
        raw_response.get("clips"), list
    ):
        raise ValueError("Director response harus berupa object dengan key 'clips'.")

    return {
        "$schema": "story_recipe_v1",
        "project_name": project_name,
        "default_settings": {
            "ratio": ratio,
            "font_style": "HORMOZI",
            "use_subtitle": True,
            "use_bgm": False,
            "min_duration": min_duration,
        },
        "clips": raw_response["clips"],
    }


def _probe_duration(video_path: str) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            video_path,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def _source_duration(source_id: str, transcripts_meta: dict) -> float:
    metadata = transcripts_meta.get(source_id, {})
    video_path = metadata.get("video_path") or metadata.get("cached_path")
    if not video_path:
        raise ValueError(f"No cached media path for source '{source_id}'.")
    return _probe_duration(video_path)


def _clamp_scene(scene: dict, transcripts_meta: dict, section: str) -> bool:
    source_id = scene.get("source_id")
    if source_id not in transcripts_meta:
        print(
            f"⚠️ Dropping {section} scene: unknown source_id '{source_id}'."
        )
        return False

    try:
        duration = _source_duration(source_id, transcripts_meta)
        start = float(scene["start"])
        end = float(scene["end"])
    except (KeyError, TypeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"⚠️ Dropping {section} scene from '{source_id}': {exc}")
        return False

    clamped_start = max(0.0, min(start, duration))
    clamped_end = max(0.0, min(end, duration))
    if clamped_start != start or clamped_end != end:
        print(
            f"⚠️ Clamped {section} scene from '{source_id}' to "
            f"[{clamped_start:.3f}, {clamped_end:.3f}] within {duration:.3f}s."
        )
    scene["start"] = clamped_start
    scene["end"] = clamped_end

    if clamped_end - clamped_start < 2.0:
        print(
            f"⚠️ Dropping {section} scene from '{source_id}': "
            f"duration {clamped_end - clamped_start:.3f}s is below 2.0s."
        )
        return False
    return True


def validate_recipe(recipe, transcripts_meta):
    """Clamp scenes, remove unusable spans, and filter invalid clip lengths."""
    defaults = recipe.setdefault("default_settings", {})
    limits = transcripts_meta.get("__director_limits__", {})
    min_duration = float(
        limits.get("min_duration", defaults.get("min_duration", 10))
    )
    max_duration = float(
        limits.get("max_duration", defaults.get("max_duration", 30))
    )
    lower_bound = min_duration * 0.85
    upper_bound = max_duration * 1.15

    valid_clips = []
    for clip in recipe.get("clips", []):
        hook = clip.get("hook", {})
        highlight = clip.get("highlight", {})
        hook_scenes = [
            scene
            for scene in hook.get("scenes", [])
            if _clamp_scene(scene, transcripts_meta, "hook")
        ]
        highlight_scenes = [
            scene
            for scene in highlight.get("scenes", [])
            if _clamp_scene(scene, transcripts_meta, "highlight")
        ]
        hook["scenes"] = hook_scenes
        highlight["scenes"] = highlight_scenes

        if not hook_scenes or not highlight_scenes:
            print(
                f"⚠️ Dropping clip {clip.get('clip_id', '?')}: "
                "hook or highlight has no usable scenes."
            )
            continue

        hook_duration = sum(
            float(scene["end"]) - float(scene["start"])
            for scene in hook_scenes
        )
        hook["duration"] = hook_duration
        total_duration = hook_duration + sum(
            float(scene["end"]) - float(scene["start"])
            for scene in highlight_scenes
        )
        if not lower_bound <= total_duration <= upper_bound:
            print(
                f"⚠️ Dropping clip {clip.get('clip_id', '?')}: "
                f"total duration {total_duration:.3f}s is outside "
                f"[{lower_bound:.3f}, {upper_bound:.3f}]s."
            )
            continue
        valid_clips.append(clip)

    recipe["clips"] = valid_clips
    return recipe


def run_director(cfg):
    """Run source preparation, Gemini recipe generation, validation, and Story."""
    sources_path = getattr(cfg, "sources_json_path", "sources.json")
    sources = loader.load_sources(sources_path)
    cache_dir = source_manager.get_cache_dir(cfg.outputs_dir)

    transcript_meta, transcripts = _load_transcript_bundle(
        sources, cache_dir, cfg
    )
    if not transcripts:
        raise RuntimeError("Director could not obtain any source transcripts.")

    print(
        f"🎬 Generating {cfg.jumlah_clip} director clip(s) with Gemini "
        f"for brief: {cfg.brief}"
    )
    gemini_started = time.perf_counter()
    recipe = generate_recipe(
        transcripts=transcripts,
        brief=cfg.brief,
        ratio=cfg.pilihan_rasio,
        min_duration=cfg.target_min,
        max_duration=cfg.target_max,
        num_clips=cfg.jumlah_clip,
        cfg=cfg,
        project_name=cfg.project_name,
    )
    transcript_meta["__director_limits__"] = {
        "min_duration": cfg.target_min,
        "max_duration": cfg.target_max,
    }
    validate_recipe(recipe, transcript_meta)
    print(f"⏱️ Gemini/director stage: {time.perf_counter() - gemini_started:.2f}s")

    recipe_path = cfg.director_recipe_out
    os.makedirs(os.path.dirname(recipe_path), exist_ok=True)
    with open(recipe_path, "w", encoding="utf-8") as f:
        json.dump(recipe, f, ensure_ascii=False, indent=2)
    print(f"💾 Validated director recipe disimpan ke: {recipe_path}")

    if getattr(cfg, "director_dry_run", False):
        return recipe

    cfg.story_recipe_path = recipe_path
    return story_runner.run_story_pipeline(cfg)
