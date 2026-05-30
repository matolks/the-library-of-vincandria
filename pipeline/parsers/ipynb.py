"""
pipeline/parsers/ipynb.py

Parse .ipynb (Jupyter notebook) files. One "page" per cell.
Code cells emit text with language="python" (or whatever the notebook declares).
Markdown cells emit text with language=None.
Outputs and metadata are ignored.
"""

import json
from pathlib import Path


def extract(filepath: str) -> list[dict]:
    with open(filepath, "r", encoding="utf-8") as f:
        nb = json.load(f)

    lang = (
        nb.get("metadata", {})
          .get("language_info", {})
          .get("name")
        or nb.get("metadata", {}).get("kernelspec", {}).get("language")
        or "python"
    )

    pages = []
    for i, cell in enumerate(nb.get("cells", []), start=1):
        cell_type = cell.get("cell_type")
        source = cell.get("source", "")
        if isinstance(source, list):
            source = "".join(source)
        source = source.strip()
        if not source:
            continue

        if cell_type == "code":
            pages.append({
                "page": i,
                "text": source,
                "language": lang,
            })
        elif cell_type == "markdown":
            pages.append({
                "page": i,
                "text": source,
                "language": None,
            })
        # raw cells skipped

    return pages
