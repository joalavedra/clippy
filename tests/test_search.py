from service import db
from service.search import build_windows, index_project, search


def _transcript():
    return {
        "source_id": "p1",
        "segmen": [
            {
                "start": 0,
                "end": 4,
                "words": [
                    {"word": "The", "start": 0, "end": 1},
                    {"word": "human", "start": 1, "end": 2},
                    {"word": "voice", "start": 2, "end": 3},
                ],
            },
            {
                "start": 4,
                "end": 11,
                "words": [
                    {"word": "carries", "start": 4, "end": 5},
                    {"word": "meaning", "start": 5, "end": 6},
                ],
            },
            {
                "start": 12,
                "end": 15,
                "words": [
                    {"word": "A", "start": 12, "end": 13},
                    {"word": "quiet", "start": 13, "end": 14},
                    {"word": "room", "start": 14, "end": 15},
                ],
            },
        ],
    }


def test_build_windows_greedily_reaches_target():
    windows = build_windows(_transcript()["segmen"], target_seconds=10)
    assert len(windows) == 2
    assert windows[0]["start"] == 0
    assert windows[0]["end"] == 11
    assert "human voice" in windows[0]["text"]


def test_index_project_is_idempotent(tmp_path):
    db_path = str(tmp_path / "search.db")
    db.create_project(db_path, id="p1", name="Project One", platform="local")
    assert index_project(db_path, "p1", _transcript()) == 2
    assert index_project(db_path, "p1", _transcript()) == 2
    conn = db.connect(db_path)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM search_windows WHERE project_id = 'p1'"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM search_fts WHERE project_id = 'p1'"
        ).fetchone()[0] == 2
    finally:
        conn.close()


def test_lexical_search_highlights_matches(tmp_path):
    db_path = str(tmp_path / "search.db")
    db.create_project(db_path, id="p1", name="Project One", platform="local")
    index_project(db_path, "p1", _transcript())
    result = search(db_path, "human voice")
    assert result["mode"] == "lexical"
    assert result["results"][0]["project_name"] == "Project One"
    assert "[human]" in result["results"][0]["highlight"]
    assert "[voice]" in result["results"][0]["highlight"]


class FakeEmbedder:
    def embed(self, texts, task):
        assert task in {"RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"}
        vectors = []
        for text in texts:
            if task == "RETRIEVAL_QUERY":
                vectors.append([1.0, 0.0])
            elif "felines" in text:
                vectors.append([0.0, 1.0])
            else:
                vectors.append([1.0, 0.0])
        return vectors


def test_hybrid_search_uses_semantic_candidates(tmp_path):
    db_path = str(tmp_path / "search.db")
    db.create_project(db_path, id="p1", name="Project One", platform="local")
    transcript = {
        "segmen": [
            {
                "start": 0,
                "end": 10,
                "words": [{"word": "cats", "start": 0, "end": 1}],
            },
            {
                "start": 10,
                "end": 20,
                "words": [{"word": "felines", "start": 10, "end": 11}],
            },
        ]
    }
    index_project(db_path, "p1", transcript, embedder=FakeEmbedder())
    result = search(db_path, "cats", embedder=FakeEmbedder())
    assert result["mode"] == "hybrid"
    assert result["results"][0]["window_id"] == "p1:0"
    assert result["results"][0]["semantic"] > 0.9


def test_fts_special_query_does_not_raise(tmp_path):
    db_path = str(tmp_path / "search.db")
    db.create_project(db_path, id="p1", name="Project One", platform="local")
    index_project(db_path, "p1", _transcript())
    result = search(db_path, '"foo" OR (bar*')
    assert result["results"] == []
