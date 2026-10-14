"""Word-aware overlapping chunker for knowledge-base documents."""
from __future__ import annotations

CHUNK_SIZE = 600  # characters
CHUNK_OVERLAP = 120  # characters


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks, never cutting a word in half.

    The overlap preserves context across chunk boundaries so an answer that
    needs the end of one chunk and the start of the next still retrieves both.
    """
    text = " ".join(text.split())  # normalize whitespace
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            # Back up to the previous space so we don't split a word.
            space = text.rfind(" ", start, end)
            if space > start:
                end = space
        chunks.append(text[start:end].strip())
        if end >= n:
            break
        # Restart with overlap, then snap forward to the next word boundary so
        # the following chunk never starts in the middle of a word. `end`
        # always sits on a space (or n, handled above), so a boundary exists.
        restart = max(end - overlap, start + 1)
        space = text.find(" ", restart, end + 1)
        start = space + 1 if space != -1 else restart
    return [c for c in chunks if c]
