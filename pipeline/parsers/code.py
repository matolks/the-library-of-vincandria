"""
Code and plain-text parser.
Reads raw text and tags with a language identifier derived from file extension.
Handles .c, .h, .v (Verilog), .py, .js, .ts, .md, .txt, and common data formats.
"""

from pathlib import Path

EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".v": "verilog",
    ".sv": "systemverilog",
    ".m": "matlab",
    ".r": "r",
    ".md": "markdown",
    ".txt": "text",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".csv": "csv",
    ".sh": "bash",
    ".tex": "latex",
}


def extract(filepath: str) -> list[dict]:
    """
    Returns [{"page": 1, "text": str, "language": str}]
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(filepath)

    language = EXTENSION_TO_LANGUAGE.get(path.suffix.lower(), "text")

    with open(str(path), "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()

    if not text.strip():
        return []

    return [{"page": 1, "text": text, "language": language}]
