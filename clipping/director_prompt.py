"""Prompt and response schema for the brief-driven "director" stage.

The director reads timestamped transcripts of one or more sources plus a
creative brief and target format, and emits a story_recipe_v1 edit plan.
"""

RECIPE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "clips": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "clip_id": {"type": "INTEGER"},
                    "title": {"type": "STRING"},
                    "viral_score": {"type": "INTEGER"},
                    "rationale": {"type": "STRING"},
                    "hook": {
                        "type": "OBJECT",
                        "properties": {
                            "type": {"type": "STRING"},
                            "text": {"type": "STRING"},
                            "duration": {"type": "NUMBER"},
                            "scenes": {
                                "type": "ARRAY",
                                "items": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "source_id": {"type": "STRING"},
                                        "start": {"type": "NUMBER"},
                                        "end": {"type": "NUMBER"},
                                        "label": {"type": "STRING"},
                                    },
                                    "required": ["source_id", "start", "end", "label"],
                                },
                            },
                        },
                        "required": ["type", "text", "duration", "scenes"],
                    },
                    "highlight": {
                        "type": "OBJECT",
                        "properties": {
                            "scenes": {
                                "type": "ARRAY",
                                "items": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "source_id": {"type": "STRING"},
                                        "start": {"type": "NUMBER"},
                                        "end": {"type": "NUMBER"},
                                        "label": {"type": "STRING"},
                                    },
                                    "required": ["source_id", "start", "end", "label"],
                                },
                            },
                            "transition": {"type": "STRING"},
                        },
                        "required": ["scenes", "transition"],
                    },
                    "metadata": {
                        "type": "OBJECT",
                        "properties": {
                            "description": {"type": "STRING"},
                            "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}},
                        },
                        "required": ["description", "hashtags"],
                    },
                },
                "required": [
                    "clip_id",
                    "title",
                    "viral_score",
                    "rationale",
                    "hook",
                    "highlight",
                    "metadata",
                ],
            },
        }
    },
    "required": ["clips"],
}


def build_director_prompt(
    transcripts: dict[str, str],
    brief: str,
    ratio: str,
    min_duration: float,
    max_duration: float,
    num_clips: int,
    language: str = "English",
) -> str:
    sources_block = "\n\n".join(
        f"=== SOURCE id=\"{sid}\" ===\n{text}" for sid, text in transcripts.items()
    )
    return f"""You are a short-form video editor and director. You will be given timestamped
transcripts of one or more source videos and a creative brief. Your job is to
produce an EDIT PLAN: {num_clips} clip(s), each assembled from one or more
verbatim spans of the sources, optimised to be shared and watched to the end
on TikTok / Reels / Shorts / X.

TRANSCRIPT FORMAT: each line is "[start - end]  words" with seconds as decimals.
Speech may be split across lines mid-sentence; the true sentence boundary is where
punctuation ends a thought.

CREATIVE BRIEF (from the producer):
{brief}

TARGET FORMAT:
- aspect ratio: {ratio}
- total duration per clip (hook + highlight): between {min_duration:.0f} and {max_duration:.0f} seconds. This is a hard constraint.
- language of titles/descriptions: {language}

RULES FOR SCENES:
1. Every scene is a span {{source_id, start, end}} that must lie inside a single
   source's transcript range. Use ONLY source_ids that appear above.
2. Cut on sentence boundaries: start at (or up to 0.3s before) the first word of a
   sentence, end at (or up to 0.4s after) the last word of a sentence. Never cut
   mid-word or mid-clause. No span shorter than 2.5 seconds.
3. Scenes within a clip may come from different sources and be non-chronological
   if that makes the story stronger, but the result must read as ONE coherent
   thought when played back to back. Prefer 1-4 scenes per clip; each scene should
   be a complete idea.
4. Do not repeat a span across clips.
5. "hook.scenes": 1 scene, the single most arresting sentence or question
   (2.5-6s) that makes a viewer stop scrolling. "hook.text" is a <=8-word on-screen
   caption that reframes it; "hook.type" is always "text_overlay"; "hook.duration"
   equals the hook scene's length.
6. "highlight.scenes": the body. It may start with the hook span again only if it
   is needed for continuity; otherwise continue from it. It must pay off the hook.
7. "highlight.transition" is always "cut".

WHAT MAKES A CLIP SHAREABLE (use these to choose and to fill viral_score 1-100):
- opens on a claim, contrast, number, or question — not on context or throat-clearing
- self-contained: needs no knowledge of the rest of the talk
- ends on a punchline, payoff, or a line people would quote
- emotional or surprising, concrete over abstract
- density: no dead air, filler, audience-logistics, or "as I said earlier"

OUTPUT: JSON only, matching the provided schema. For each clip give
"rationale" (1-2 sentences: why this will perform, referencing the brief),
"title" (curiosity-driven, <=60 chars, no clickbait lies), "metadata.description"
(1-2 sentences) and 3-6 "metadata.hashtags" without the # symbol.
Order clips by viral_score descending and number clip_id from 1.

SOURCES:

{sources_block}
"""
