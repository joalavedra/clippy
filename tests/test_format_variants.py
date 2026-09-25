from types import SimpleNamespace

import pytest

from clipping.config import build_config
from clipping import director


def test_formats_parse_variants_and_keep_old_syntax():
    config = build_config(
        ["--director", "--formats", "9:16/8-12+16:9+1:1,16:9/20-30"]
    )
    assert config.formats == [
        ("9:16", 8.0, 12.0, ["16:9", "1:1"]),
        ("16:9", 20.0, 30.0, []),
    ]


@pytest.mark.parametrize(
    "spec",
    ["9:16/8-12+16:9+16:9", "9:16/8-12+9:16"],
)
def test_formats_reject_duplicate_or_primary_variants(spec):
    with pytest.raises(SystemExit):
        build_config(["--director", "--formats", spec])


def test_run_director_renders_variants_from_one_recipe(tmp_path, monkeypatch):
    cfg = SimpleNamespace(
        sources_json_path=str(tmp_path / "sources.json"),
        outputs_dir=str(tmp_path / "outputs"),
        story_cache_dir=str(tmp_path / "cache"),
        director_recipe_out=str(tmp_path / "director_recipe.json"),
        formats=[("9:16", 8.0, 12.0, ["16:9"])],
        project_name="Variants",
        brief="brief",
        jumlah_clip=1,
        pilihan_rasio="9:16",
        target_min=8,
        target_max=12,
        director_dry_run=False,
        story_style="styled",
        clean_speech=False,
    )
    recipe = {
        "clips": [
            {
                "clip_id": 1,
                "title": "Clip",
                "hook": {"scenes": [{"source_id": "source", "start": 0, "end": 4}]},
                "highlight": {"scenes": [{"source_id": "source", "start": 4, "end": 8}]},
            }
        ]
    }
    calls = []
    stages = []

    monkeypatch.setattr(
        director.loader,
        "load_sources",
        lambda path: {"source": {"layout": "single"}},
    )
    monkeypatch.setattr(
        director,
        "_load_transcript_bundle",
        lambda sources, cache_dir, cfg: ({"source": {"segmen": []}}, {"source": "text"}),
    )
    monkeypatch.setattr(
        director,
        "generate_recipe",
        lambda **kwargs: recipe.copy(),
    )
    monkeypatch.setattr(director, "validate_recipe", lambda recipe, metadata, cfg=None: recipe)

    def render(current_cfg):
        calls.append((current_cfg.pilihan_rasio, current_cfg.story_output_dir))
        return [{"clip_id": 1, "final_path": f"{current_cfg.pilihan_rasio}.mp4"}]

    monkeypatch.setattr(director.story_runner, "run_story_pipeline", render)
    results = director.run_director(cfg, on_stage=lambda stage, label: stages.append((stage, label)))

    assert len(calls) == 2
    assert calls[0] == ("9:16", str(tmp_path / "outputs" / "Variants" / "9x16"))
    assert calls[1] == (
        "16:9",
        str(tmp_path / "outputs" / "Variants" / "9x16" / "16x9"),
    )
    assert cfg.pilihan_rasio == "9:16"
    assert results[0]["variants"][0]["format"] == "16:9"
    assert results[0]["variants"][0]["slug"] == "9x16_16x9"
    assert ("render", "9:16>16:9") in stages
