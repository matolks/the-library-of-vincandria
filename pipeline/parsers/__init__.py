"""
Parser dispatch. Call parse(filepath) from anywhere in the pipeline.
Returns list of dicts with at minimum: {"page": int, "text": str}
Code files also include: {"language": str}
"""

from pathlib import Path
from pipeline.parsers import pdf, docx, xlsx, code, pptx, ipynb

PDF_EXTENSIONS = {".pdf"}
DOCX_EXTENSIONS = {".docx"}
XLSX_EXTENSIONS = {".xlsx", ".xls"}
PPTX_EXTENSIONS = {".pptx"}
IPYNB_EXTENSIONS = {".ipynb"}
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".c", ".h", ".cpp",
    ".v", ".sv", ".m", ".r", ".md", ".txt",
    ".json", ".yaml", ".yml", ".csv", ".sh", ".tex",
}

ALL_SUPPORTED = (
    PDF_EXTENSIONS
    | DOCX_EXTENSIONS
    | XLSX_EXTENSIONS
    | PPTX_EXTENSIONS
    | IPYNB_EXTENSIONS
    | CODE_EXTENSIONS
)


def parse(filepath: str) -> list[dict]:
    suffix = Path(filepath).suffix.lower()
    if suffix in PDF_EXTENSIONS:
        return pdf.extract(filepath)
    elif suffix in DOCX_EXTENSIONS:
        return docx.extract(filepath)
    elif suffix in XLSX_EXTENSIONS:
        return xlsx.extract(filepath)
    elif suffix in PPTX_EXTENSIONS:
        return pptx.extract(filepath)
    elif suffix in IPYNB_EXTENSIONS:
        return ipynb.extract(filepath)
    elif suffix in CODE_EXTENSIONS:
        return code.extract(filepath)
    else:
        raise ValueError(f"Unsupported file type: {suffix}  ({filepath})")


def is_supported(filepath: str) -> bool:
    return Path(filepath).suffix.lower() in ALL_SUPPORTED
