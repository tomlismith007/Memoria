"""Parse PDF / Markdown / plain text / web pages into plain text."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import requests
from pypdf import PdfReader


@dataclass
class Document:
    doc_id: str  # hash of origin only: re-ingesting the same path replaces its vectors
    text: str
    origin: str  # file path or URL


def _doc_id(origin: str) -> str:
    return hashlib.sha256(origin.encode("utf-8")).hexdigest()[:16]


def load_document(source: str) -> Document:
    """Load any supported source into a Document. Dispatch by URL vs suffix."""
    if source.startswith(("http://", "https://")):
        return Document(_doc_id(source), _parse_url(source), source)
    path = Path(source)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text = _parse_pdf(path)
    else:  # .md / .markdown / .txt / anything else: best-effort UTF-8 read
        text = path.read_text(encoding="utf-8")
    return Document(_doc_id(str(path)), text, str(path))


def _parse_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _parse_url(url: str) -> str:
    html = requests.get(url, timeout=30).text
    # ponytail: regex tag-strip; trafilatura if extraction quality ever matters
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()
