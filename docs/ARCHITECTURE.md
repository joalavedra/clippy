# Clippy — platform architecture

Goal: given one or more video sources and a creative brief, produce platform-ready
clips in requested formats (e.g. 16:9 / 30 s, 9:16 / 10 s), ranked by expected
shareability, and eventually learn from real platform performance.

This document describes the current state of the engine (forked from
`opensource-clipping`, extended with the director stage), the target platform
around it, and the order in which to build the remaining pieces.

## 1. Pipeline

```
 sources ──► ingest ──► transcribe ──► direct ──► edit plan ──► render ──► publish ──► learn
 (URLs,       cache      word-level    brief +   story_recipe   reframe,    per-       perf →
  files)      + probe    Whisper       formats   _v1 JSON       captions,   platform   scoring
                                                                concat      metadata
```

Every arrow is a file on disk, so each stage can be re-run, inspected, or edited
by hand / in a UI without re-running the stages before it.

| Stage | Current implementation | Status |
|---|---|---|
| Ingest | `clipping/engine.download_video` (yt-dlp), `clipping/story/source_manager.py` (multi-source cache), `--file` local input | done |
| Transcribe | faster-whisper, word timestamps, cached per source in `outputs/story_cache` | done |
| Direct | `clipping/director.py` + `director_prompt.py`: brief + transcripts + per-format targets → Gemini structured JSON → validated `story_recipe_v1` | done (v1) |
| Edit plan | `story_recipe_v1` (`docs/STORY_CLIP.md`): scenes `{source_id,start,end}`, hook + highlight, transition, ratio, captions, metadata | done |
| Render | `clipping/story/styled_render.py` per scene: face-tracked reframe (`studio/render_hybrid.py`), ASS karaoke captions (`studio/subtitles.py`), MPEG-TS concat; `studio/camera_path.py` aligns crop snaps and layout switches to detected shot cuts | done (single-speaker); split-screen / camera-switch exist only in the main pipeline |
| Publish | YouTube / Facebook uploaders in the main pipeline; metadata in the recipe | partial |
| Learn | — | not started |

### 1.1 Director stage (the product-specific part)

Input: transcripts of N sources, a natural-language brief, and a list of format
specs (`--formats 16:9/20-30,9:16/8-12`). One Gemini call per format with a
format-specific editorial strategy (`director_prompt.format_guidance`): micro
clips (≤15 s) are one idea, short clips (≤45 s) are hook → argument → payoff,
long clips are mini-stories; vertical vs landscape changes what visual material
is acceptable.

Output is a `story_recipe_v1` document. Post-processing in `director.validate_recipe`:

- clamps scenes to real source durations (ffprobe), drops unusable scenes;
- `snap_scene_to_words` moves each boundary onto a transcript word and extends
  the end forward (≤4 s) to sentence punctuation, so cuts never land mid-word
  or mid-clause;
- enforces the per-format duration window.

The LLM only ever sees text and only emits timestamps and metadata; all pixel
decisions are made deterministically by the renderer. This keeps the expensive
part re-runnable (a new brief = one more Gemini call, no re-transcription) and
keeps quality issues attributable (selection vs. cutting vs. rendering).

### 1.2 Render stage

Per scene: trim → reframe → captions → encode to `.ts`; per clip: concat `.ts`
→ mp4. Reframing for vertical output tracks the largest face, with a deadzone
and smoothing; shot cuts are detected by frame differencing once per clip and
every camera snap / layout change is stepped exactly on the cut frame instead of
being interpolated across sample intervals (this was the cause of the "weird
lateral transitions"). Landscape output uses scale+pad.

## 2. Platform around the engine

```
                ┌──────────────┐     ┌──────────────┐
 web UI ──────► │  API (jobs)  │ ──► │  worker(s)   │ ──► object storage (sources, cache, clips)
 (brief, picks) │  Postgres    │     │  engine CLI  │
                └──────────────┘     └──────────────┘
                        ▲                    │
                        └── performance ◄────┘ publish (YouTube / TikTok / Meta / X APIs)
```

- **Jobs**: one job = sources + brief + formats. Stages map to job steps with
  their artifacts (transcripts, recipes, renders) stored and addressable, so the
  UI can show the recipe, let a human edit spans/titles, and re-render only.
- **Workers**: the engine already runs as a CLI with all state on disk, so a
  worker is "check out inputs → run `main.py --director …` → upload outputs".
  Rendering is CPU-bound (libx264); GPU workers help Whisper and encoding.
- **Storage**: keep the per-source transcription cache; it is the most expensive
  artifact and is reused across every brief.
- **Publish**: reuse the existing uploaders; add TikTok/X. Store the returned
  post IDs per rendered clip.
- **Learn**: poll platform analytics (views, completion, shares) per post ID and
  attach them to the recipe's clip. First use: an evaluation set of
  (brief, transcript excerpt, chosen spans, outcome) to tune the prompt's
  "what makes a clip shareable" section and the viral_score calibration; later,
  a small ranking model over candidate spans.

### 2.1 Service layer v1 (`service/`)

Implemented as a single process to start (API + one worker thread, SQLite,
local disk), with the seams needed to split it later. Object model follows
`docs/DESIGN_SYSTEM.md` §1 so a Library UI can sit directly on it.

```
projects   id, name, platform, url|local_path, layout, created_at        (= a source)
jobs       id, brief, formats(json), clips, options(json), project_ids(json),
           status queued|running|done|failed, stage, percent, error, created/updated
job_events id, job_id, ts, stage, message
assets     id, job_id, project_ids(json), clip_id, title, hook_line, rationale,
           viral_score, hashtags(json), metadata(json), state, favorite, created_at
renders    id, asset_id, ratio, duration, file_key, thumb_key, recipe_clip(json)
```

- `service/db.py` — sqlite3 (WAL), schema above, thin repository functions.
- `service/storage.py` — `Storage` protocol (`put(path, key) -> key`,
  `url(key)`), `LocalStorage(root)` served at `/files/{key}`. S3 later.
  API responses sign media URLs with short-lived per-file tokens when media
  signing is configured; the signing secret is derived from the API key unless
  `CLIPPY_MEDIA_SECRET` is set. The files route accepts those tokens or the
  API-key header, but never API keys in query parameters.
- `service/worker.py` — background thread; picks `queued` jobs, writes a
  per-job `sources.json`, builds the engine config with
  `clipping.config.build_config(argv)` exactly as the CLI would, calls
  `director.run_director(cfg, on_stage=...)`, then catalogs the returned
  recipes + Story manifests into `assets`/`renders`, copying finals into
  storage. Stages: `prepare` → `transcribe` → `direct:<ratio>` →
  `render:<ratio>` → `catalog`.
- `service/app.py` — FastAPI:

```
POST /api/projects            {name, platform, url|local_path, layout}
GET  /api/projects
POST /api/jobs                {project_ids, brief, formats:[{ratio,min,max}], clips, options}
GET  /api/jobs  /api/jobs/{id}  /api/jobs/{id}/events
GET  /api/assets?job_id&project_id&ratio&min_score&state&favorite
GET  /api/assets/{id}
PATCH /api/assets/{id}        {state?, favorite?}
GET  /api/health
```

Not in v1: multiple workers/queue (swap the thread for a queue consumer),
publishing, covers, search. The API key and local-media-root checks define the
v1 trust boundary for this local service; signed media URLs provide scoped,
short-lived access to rendered files. Production auth and identity are still
future work. `web/api` (upstream GUI for the single-URL pipeline) is
left untouched.

## 3. Known gaps / next work (priority order)

1. **Two-speaker output in director mode** — port split-screen / camera-switch
   from the main pipeline into `styled_render` so a Story scene of a podcast
   gets the podcast layout (needs pyannote + HF token for audio-driven mode;
   face-triggered mode works today).
2. **Multi-source mixing** — the director still prefers single-source clips
   even when the brief allows mixing; add an explicit `mix_sources` intent and
   evaluation.
3. **Hook overlay & caption styling per format** — landscape captions are
   small and sit at the frame edge; hook text overlay needs a 16:9 layout.
4. **Hook→main "glitch" transition** renders as 0.3 s of black when the glitch
   asset is unavailable; make it optional/local.
5. **Candidate over-generation + ranking** — ask the director for 2–3× the
   requested clips, render cheap previews, rank, then render finals.
6. **Tests** — `snap_scene_to_words`, crossfade offsets, camera_path stepping,
   recipe validation, duration windows.
7. **Service layer** — job API + worker + storage as above.

## 4. Running it

```bash
# one brief, two formats, two clips each, styled render
python main.py --director --sources-json sources.json \
  --brief "Practical, surprising advice on how to be heard when you speak" \
  --formats 16:9/20-30,9:16/8-12 --clips 2 --gemini-timeout 180

# local file through the main pipeline (podcast split-screen)
python main.py --file podcast.mp4 --output-dir outputs/podcast \
  --ratio 9:16 --clips 2 --split-screen --split-trigger face --dynamic-split
```
