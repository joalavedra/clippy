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
    response_path=None,
    source_layouts=None,
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
        source_layouts=source_layouts,
    )
    client = genai.Client(
        api_key=cfg.api_key_gemini,
        http_options=types.HttpOptions(
            timeout=int(
                getattr(
                    cfg,
                    "gemini_timeout",
                    engine.DEFAULT_GEMINI_TIMEOUT_SECONDS,
                )
                * 1000
            ),
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
        retry_wait_seconds=getattr(
            cfg,
            "gemini_retry_wait",
            engine.DEFAULT_GEMINI_RETRY_WAIT_SECONDS,
        ),
    )

    response_path = response_path or os.path.join(
        cfg.outputs_dir, "director_response.json"
    )
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


def snap_scene_to_words(scene: dict, segmen: list[dict]) -> bool:
    """Snap scene boundaries to nearby transcript word timestamps."""
    words = []
    for segment in segmen or []:
        for word in segment.get("words", []):
            try:
                words.append(
                    {
                        "word": str(word["word"]),
                        "start": float(word["start"]),
                        "end": float(word["end"]),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
    words.sort(key=lambda word: (word["start"], word["end"]))
    if not words:
        return False

    old_start = float(scene["start"])
    old_end = float(scene["end"])
    new_start = old_start
    new_end = old_end

    start_matches = [
        word for word in words if abs(word["start"] - old_start) <= 0.6
    ]
    start_word = min(
        start_matches,
        key=lambda word: abs(word["start"] - old_start),
        default=None,
    )
    if start_word is not None:
        start_index = words.index(start_word)
        candidate_start = max(0.0, start_word["start"] - 0.15)
        if start_index:
            candidate_start = max(candidate_start, words[start_index - 1]["end"])
        new_start = candidate_start

    end_matches = [
        word for word in words if abs(word["end"] - old_end) <= 0.6
    ]
    end_word = min(
        end_matches,
        key=lambda word: abs(word["end"] - old_end),
        default=None,
    )
    if end_word is not None:
        end_index = words.index(end_word)
        punctuation = '.?!…'
        text = end_word["word"].strip().rstrip(
            "\"'”’)]}》」』"
        )
        if not text.endswith(tuple(punctuation)):
            for candidate in words[end_index + 1 :]:
                candidate_text = candidate["word"].strip().rstrip(
                    "\"'”’)]}》」』"
                )
                if candidate_text.endswith(tuple(punctuation)):
                    if candidate["end"] - end_word["end"] <= 4.0:
                        end_word = candidate
                        end_index = words.index(candidate)
                    break

        candidate_end = end_word["end"] + 0.25
        if end_index + 1 < len(words):
            candidate_end = min(candidate_end, words[end_index + 1]["start"] - 0.05)
            candidate_end = max(candidate_end, end_word["end"])
        new_end = candidate_end

    scene["start"] = new_start
    scene["end"] = new_end
    return new_start != old_start or new_end != old_end


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

    metadata = transcripts_meta[source_id]
    old_start, old_end = scene["start"], scene["end"]
    snap_scene_to_words(scene, metadata.get("segmen", []))
    if (
        abs(scene["start"] - old_start) > 0.05
        or abs(scene["end"] - old_end) > 0.05
    ):
        snapped_end_word = ""
        for segment in metadata.get("segmen", []):
            for word in segment.get("words", []):
                if abs(float(word.get("end", -1)) - (scene["end"] - 0.25)) < 0.3:
                    snapped_end_word = str(word.get("word", "")).strip()
        print(
            f'🔧 snapped {source_id} '
            f'[{old_start:.2f}→{scene["start"]:.2f}, '
            f'{old_end:.2f}→{scene["end"]:.2f}]'
            + (f' ends on "{snapped_end_word}"' if snapped_end_word else "")
        )

    if scene["end"] - scene["start"] < 2.0:
        print(
            f"⚠️ Dropping {section} scene from '{source_id}': "
            f"duration {scene['end'] - scene['start']:.3f}s is below 2.0s."
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


def run_director(cfg, on_stage=None):
    """Run source preparation, Gemini recipe generation, validation, and Story."""
    sources_path = getattr(cfg, "sources_json_path", "sources.json")
    sources = loader.load_sources(sources_path)
    cache_dir = source_manager.get_cache_dir(
        cfg.outputs_dir,
        getattr(cfg, "story_cache_dir", None),
    )

    if on_stage:
        on_stage("transcribe", "")
    transcript_meta, transcripts = _load_transcript_bundle(
        sources, cache_dir, cfg
    )
    if not transcripts:
        raise RuntimeError("Director could not obtain any source transcripts.")
    source_layouts = {
        sid: source.get("layout", "single")
        for sid, source in sources.items()
    }

    format_specs = getattr(cfg, "formats", None) or [
        (cfg.pilihan_rasio, cfg.target_min, cfg.target_max)
    ]
    recipe_stem, recipe_ext = os.path.splitext(cfg.director_recipe_out)
    if not recipe_ext:
        recipe_ext = ".json"
    all_results = []
    summary_rows = []

    for ratio, min_duration, max_duration in format_specs:
        slug = ratio.replace(":", "x")
        recipe_path = (
            f"{recipe_stem}_{slug}{recipe_ext}"
            if getattr(cfg, "formats", None)
            else cfg.director_recipe_out
        )
        response_path = (
            os.path.join(cfg.outputs_dir, f"director_response_{slug}.json")
            if getattr(cfg, "formats", None)
            else os.path.join(cfg.outputs_dir, "director_response.json")
        )
        print(
            f"🎬 Generating {cfg.jumlah_clip} director clip(s) with Gemini "
            f"for {ratio} [{min_duration:g}-{max_duration:g}s] "
            f"and brief: {cfg.brief}"
        )
        if on_stage:
            on_stage("direct", ratio)
        gemini_started = time.perf_counter()
        recipe = generate_recipe(
            transcripts=transcripts,
            brief=cfg.brief,
            ratio=ratio,
            min_duration=min_duration,
            max_duration=max_duration,
            num_clips=cfg.jumlah_clip,
            cfg=cfg,
            project_name=cfg.project_name,
            response_path=response_path,
            source_layouts=source_layouts,
        )
        transcript_meta["__director_limits__"] = {
            "min_duration": min_duration,
            "max_duration": max_duration,
        }
        validate_recipe(recipe, transcript_meta)
        print(
            f"⏱️ Gemini/director stage ({ratio}): "
            f"{time.perf_counter() - gemini_started:.2f}s"
        )

        os.makedirs(os.path.dirname(recipe_path), exist_ok=True)
        with open(recipe_path, "w", encoding="utf-8") as f:
            json.dump(recipe, f, ensure_ascii=False, indent=2)
        print(f"💾 Validated director recipe disimpan ke: {recipe_path}")

        cfg.pilihan_rasio = ratio
        cfg.target_min = min_duration
        cfg.target_max = max_duration
        cfg.story_recipe_path = recipe_path
        if getattr(cfg, "formats", None):
            cfg.story_output_dir = os.path.join(
                cfg.outputs_dir, cfg.project_name, slug
            )
        if getattr(cfg, "story_style", None) is None:
            cfg.story_style = "styled"

        render_result = None
        if not getattr(cfg, "director_dry_run", False):
            if on_stage:
                on_stage("render", ratio)
            render_result = story_runner.run_story_pipeline(cfg)
        all_results.append(
            {
                "format": ratio,
                "slug": slug,
                "recipe_path": recipe_path,
                "response_path": response_path,
                "render": render_result,
                "recipe": recipe,
            }
        )
        for clip in recipe.get("clips", []):
            hook_scenes = clip.get("hook", {}).get("scenes", [])
            highlight_scenes = clip.get("highlight", {}).get("scenes", [])
            duration = sum(
                float(scene["end"]) - float(scene["start"])
                for scene in hook_scenes + highlight_scenes
            )
            sources_used = sorted(
                {
                    scene["source_id"]
                    for scene in hook_scenes + highlight_scenes
                }
            )
            summary_rows.append(
                (
                    ratio,
                    clip.get("clip_id", "?"),
                    clip.get("title", ""),
                    duration,
                    len(hook_scenes) + len(highlight_scenes),
                    ", ".join(sources_used),
                )
            )

    print("\nDirector format summary")
    print("Format | Clip | Title | Duration | Scenes | Sources")
    print("-" * 100)
    for ratio, clip_id, title, duration, scene_count, sources_used in summary_rows:
        print(
            f"{ratio:>5} | {clip_id:>4} | {title[:35]:<35} | "
            f"{duration:>7.2f}s | {scene_count:>6} | {sources_used}"
        )
    if getattr(cfg, "director_dry_run", False) and not getattr(
        cfg, "formats", None
    ):
        return all_results[0]["recipe"]
    return all_results
