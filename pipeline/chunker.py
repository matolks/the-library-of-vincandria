"""
pipeline/chunker.py

Stage 1: parse files -> extract text -> chunk into passages.
No Claude API calls. Everything runs locally.

Chunking strategy: sliding window over words (ported from original ingest.py).
Ollama is used optionally to clean/summarize each chunk before it leaves this stage.
Set OLLAMA_SUMMARIZE=false in .env to skip and use raw chunks.

Output schema per chunk:
{
    "course": str,
    "file": str,
    "page": int,
    "chunk_index": int,
    "text": str,
    "source_type": str,       # lectures | exams | homework | reference | topics | other
    "language": str | None    # only for code files
}
"""

import os
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

AISTACK_DOCS = os.getenv(
    "AISTACK_DOCS", "/Volumes/AIStack/modules/knowledge/docs")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
OLLAMA_SUMMARIZE = os.getenv("OLLAMA_SUMMARIZE", "false").lower() == "true"

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "400"))     # words
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))  # words

KNOWN_SOURCE_TYPES = {"lectures", "exams", "homework", "reference", "topics"}


# ---------------------------------------------------------------------------
# Text chunking
# ---------------------------------------------------------------------------

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunks.append(" ".join(words[start:end]))
        start += chunk_size - overlap
    return chunks


# ---------------------------------------------------------------------------
# Optional Ollama pass to clean chunk text
# ---------------------------------------------------------------------------

def _ollama_clean(text: str) -> str:
    try:
        import ollama
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a text cleaner. Given a raw passage extracted from a course document, "
                        "remove headers, footers, page numbers, and OCR artifacts. "
                        "Return only clean prose. Do not add, interpret, or summarize. "
                        "If the passage is already clean, return it unchanged."
                    ),
                },
                {"role": "user", "content": text},
            ],
        )
        return response["message"]["content"].strip() or text
    except Exception as e:
        print(f"  [ollama] clean failed, using raw text: {e}")
        return text


# ---------------------------------------------------------------------------
# Source type inference
# ---------------------------------------------------------------------------

def _infer_source_type(filepath: Path, course_dir: Path) -> str:
    """
    Source type = first path component under the course root, lowercased.
    Files at the course root (no subfolder) get 'other'.
    Unknown folder names are returned as-is so the user notices instead
    of silently bucketing into 'other'.
    """
    try:
        rel = filepath.relative_to(course_dir)
    except ValueError:
        return "other"

    parts = rel.parts
    if len(parts) < 2:
        return "other"

    first = parts[0].lower()
    return first if first in KNOWN_SOURCE_TYPES else first


# ---------------------------------------------------------------------------
# Per-file chunking
# ---------------------------------------------------------------------------

def chunk_file(filepath: str, course: str, source_type: str = "other") -> list[dict]:
    from pipeline.parsers import parse, is_supported

    if not is_supported(filepath):
        return []

    pages = parse(filepath)
    filename = Path(filepath).name
    chunks = []
    global_index = 0

    for page_data in pages:
        page_num = page_data["page"]
        text = page_data["text"]
        language = page_data.get("language")

        for chunk_text_raw in chunk_text(text):
            if not chunk_text_raw.strip():
                continue

            cleaned = _ollama_clean(
                chunk_text_raw) if OLLAMA_SUMMARIZE else chunk_text_raw

            chunk = {
                "course": course,
                "file": filename,
                "page": page_num,
                "chunk_index": global_index,
                "text": cleaned.replace("\x00", ""),
                "source_type": source_type,
            }
            if language:
                chunk["language"] = language

            chunks.append(chunk)
            global_index += 1

    return chunks


# ---------------------------------------------------------------------------
# Per-course chunking
# ---------------------------------------------------------------------------

def chunk_course(course: str, single_file: str | None = None) -> list[dict]:
    from pipeline.parsers import is_supported

    course_dir = Path(AISTACK_DOCS) / course
    if not course_dir.exists():
        raise FileNotFoundError(f"Course directory not found: {course_dir}")

    if single_file:
        files = [course_dir / single_file]
    else:
        files = [f for f in course_dir.rglob(
            "*") if f.is_file() and is_supported(str(f))]

    if not files:
        print(f"No supported files found in {course_dir}")
        return []

    # Summary of what was found, grouped by source_type
    found_by_type: dict[str, int] = {}
    for f in files:
        st = _infer_source_type(f, course_dir)
        found_by_type[st] = found_by_type.get(st, 0) + 1
    print("Files by source_type:", found_by_type)

    unknown = {
        t for t in found_by_type if t not in KNOWN_SOURCE_TYPES and t != "other"}
    if unknown:
        print(f"  [warn] unknown source_type folder(s): {sorted(unknown)} "
              f"(expected one of {sorted(KNOWN_SOURCE_TYPES)})")

    all_chunks = []
    for f in files:
        source_type = _infer_source_type(f, course_dir)
        print(f"  Parsing {f.name} [{source_type}]...")
        file_chunks = chunk_file(str(f), course, source_type=source_type)
        print(f"    -> {len(file_chunks)} chunks")
        all_chunks.extend(file_chunks)

    return all_chunks


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Chunk course files (Stage 1).")
    parser.add_argument("--course", required=True,
                        help="Course directory name under AISTACK_DOCS")
    parser.add_argument("--file", default=None,
                        help="Single file to chunk (optional)")
    parser.add_argument("--out", default=None,
                        help="Write chunk JSON to this path (optional)")
    args = parser.parse_args()

    print(f"Chunking: {args.course}" +
          (f" / {args.file}" if args.file else ""))
    chunks = chunk_course(args.course, args.file)
    print(f"\nTotal chunks: {len(chunks)}")

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(chunks, f, indent=2)
        print(f"Written to {out_path}")
    else:
        for c in chunks[:3]:
            print(json.dumps(c, indent=2))
