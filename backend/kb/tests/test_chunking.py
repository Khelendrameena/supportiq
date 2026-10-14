"""Unit tests for the word-aware overlapping chunker."""
from kb.chunking import chunk_text


def test_empty_text_gives_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_short_text_is_one_chunk():
    assert chunk_text("hello world") == ["hello world"]


def test_chunks_never_split_words():
    text = " ".join(f"word{i:04d}" for i in range(200))  # long, uniform words
    chunks = chunk_text(text, size=100, overlap=20)
    for chunk in chunks:
        assert len(chunk) <= 100
        # Rejoining with single spaces must reproduce whole words only.
        assert all(w.startswith("word") for w in chunk.split())


def test_overlap_preserves_context():
    text = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
    chunks = chunk_text(text, size=30, overlap=15)
    assert len(chunks) > 1
    # Every chunk after the first shares words with its predecessor.
    for prev, cur in zip(chunks, chunks[1:]):
        assert set(prev.split()) & set(cur.split())


def test_full_coverage_no_gaps():
    text = " ".join(f"token{i}" for i in range(500))
    chunks = chunk_text(text, size=200, overlap=50)
    # Every word of the input must appear in at least one chunk (no gaps),
    # and chunks must be in document order.
    joined = " ".join(chunks)
    for word in text.split():
        assert word in joined
    positions = [joined.index(f"token{i}") for i in (0, 250, 499)]
    assert positions == sorted(positions)
