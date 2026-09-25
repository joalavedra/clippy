import pytest

from clipping.director import clean_scene_speech
from clipping.story.timeline_view import map_words_to_output


def _word(word, start, end):
    return {"word": word, "start": start, "end": end}


def test_clean_scene_speech_removes_fillers():
    scene = {"source_id": "source", "start": 0, "end": 5, "label": "speech"}
    segments = [{"words": [_word("Hello", 0.2, 1.4), _word("um,", 1.5, 1.8), _word("world", 1.9, 3.2)]}]
    cleaned = clean_scene_speech(scene, segments)
    assert len(cleaned) == 2
    assert all(item["source_id"] == "source" for item in cleaned)
    assert cleaned[0]["start"] == pytest.approx(0.15)
    assert cleaned[0]["end"] == pytest.approx(1.48)
    assert cleaned[1]["start"] == pytest.approx(1.85)
    assert cleaned[1]["end"] == pytest.approx(3.28)


def test_clean_scene_speech_splits_long_gaps():
    scene = {"source_id": "source", "start": 0, "end": 6}
    segments = [{"words": [_word("first", 0.2, 1.5), _word("second", 2.4, 3.8)]}]
    cleaned = clean_scene_speech(scene, segments)
    assert len(cleaned) == 2
    assert cleaned[0]["start"] == pytest.approx(0.15)
    assert cleaned[0]["end"] == pytest.approx(1.58)
    assert cleaned[1]["start"] == pytest.approx(2.35)
    assert cleaned[1]["end"] == pytest.approx(3.88)


def test_clean_scene_speech_merges_short_subscene():
    scene = {"source_id": "source", "start": 0, "end": 6}
    segments = [{"words": [_word("long", 0.2, 1.5), _word("tiny", 2.4, 2.6)]}]
    cleaned = clean_scene_speech(scene, segments)
    assert len(cleaned) == 1
    assert cleaned[0]["start"] == pytest.approx(0.15)
    assert cleaned[0]["end"] == pytest.approx(2.68)


def test_clean_scene_speech_padding_clamps_to_scene():
    scene = {"source_id": "source", "start": 1, "end": 3}
    segments = [{"words": [_word("start", 1, 1.3), _word("end", 2.7, 3)]}]
    cleaned = clean_scene_speech(scene, segments)
    assert cleaned[0]["start"] == pytest.approx(1)
    assert cleaned[0]["end"] == pytest.approx(3)


def test_map_words_to_output():
    scenes = [
        {"source_id": "a", "start": 10, "end": 12, "offset": 0},
        {"source_id": "b", "start": 4, "end": 6, "offset": 2},
    ]
    transcripts = {
        "a": {"segmen": [{"words": [_word("one", 10.2, 10.7)]}]},
        "b": {"segmen": [{"words": [_word("two", 4.5, 5.1)]}]},
    }
    mapped = map_words_to_output(scenes, transcripts)
    assert [word["word"] for word in mapped] == ["one", "two"]
    assert mapped[0]["start"] == pytest.approx(0.2)
    assert mapped[0]["end"] == pytest.approx(0.7)
    assert mapped[1]["start"] == pytest.approx(2.5)
    assert mapped[1]["end"] == pytest.approx(3.1)
