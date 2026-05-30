"""
PDF parser using pymupdf (fitz).
Extracts text page by page, preserving page numbers for chunk metadata.
"""

from pathlib import Path


def extract(filepath: str) -> list[dict]:
    """
    Returns a list of page dicts: {"page": int, "text": str}
    Pages with no extractable text are skipped.
    """
    try:
        import fitz  # pymupdf
    except ImportError:
        raise ImportError("pymupdf is required: pip install pymupdf")

    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(filepath)

    doc = fitz.open(str(path))
    pages = []

    for i, page in enumerate(doc, start=1):
        text = page.get_text("text").strip()
        if text:
            pages.append({"page": i, "text": text})

    doc.close()
    return pages
