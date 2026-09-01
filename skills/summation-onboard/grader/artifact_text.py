"""Extract the user-visible text from supported report artifacts."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from html.parser import HTMLParser
import html
from pathlib import Path
import re
import shutil
import subprocess


REPORT_SUFFIXES = frozenset({
    ".html", ".htm", ".md", ".markdown", ".txt", ".csv",
    ".xlsx", ".pptx", ".docx", ".pdf",
})


@dataclass(frozen=True)
class ExtractedArtifact:
    path: Path
    text: str
    method: str
    sha256: str
    bytes: int

    @property
    def format(self) -> str:
        return self.path.suffix.lower().lstrip(".") or "unknown"


class _VisibleHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style"}:
            self.hidden += 1
        elif tag.lower() in {"br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style"} and self.hidden:
            self.hidden -= 1
        elif tag.lower() in {"td", "th"}:
            self.parts.append("\t")
        elif tag.lower() in {"p", "div", "tr", "li", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)

    def text(self) -> str:
        lines = [re.sub(r"[ \t]+", " ", line).strip()
                 for line in "".join(self.parts).splitlines()]
        return "\n".join(line for line in lines if line)


def find_report(root: Path) -> Path:
    direct = [p for p in sorted(root.iterdir())
              if p.is_file() and p.suffix.lower() in REPORT_SUFFIXES]
    if len(direct) != 1:
        shown = ", ".join(p.name for p in direct) or "none"
        raise ValueError(f"expected one top-level report, found {len(direct)}: {shown}")
    return direct[0]


def _office_text(path: Path) -> str:
    binary = shutil.which("officecli")
    if not binary:
        raise RuntimeError(
            f"{path.suffix.upper()} needs OfficeCLI. Install it or provide HTML/Markdown.")
    result = subprocess.run(
        [binary, "view", str(path), "text"], capture_output=True, text=True,
        timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"OfficeCLI could not read {path.name}: "
                           f"{(result.stderr or result.stdout).strip()[:500]}")
    return result.stdout.strip()


def _pdf_text(path: Path) -> str:
    binary = shutil.which("pdftotext")
    if not binary:
        raise RuntimeError("PDF needs pdftotext (Poppler) for receipted extraction")
    result = subprocess.run(
        [binary, "-layout", str(path), "-"], capture_output=True, text=True,
        timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"pdftotext could not read {path.name}: {result.stderr[:500]}")
    return result.stdout.strip()


def extract(path: Path) -> ExtractedArtifact:
    path = path.resolve()
    suffix = path.suffix.lower()
    raw = path.read_bytes()
    if suffix in {".html", ".htm"}:
        parser = _VisibleHTML()
        parser.feed(raw.decode("utf-8", errors="replace"))
        text, method = parser.text(), "html-parser"
    elif suffix in {".md", ".markdown", ".txt", ".csv"}:
        text, method = raw.decode("utf-8", errors="replace"), "plain-text"
    elif suffix in {".xlsx", ".pptx", ".docx"}:
        text, method = _office_text(path), "officecli"
    elif suffix == ".pdf":
        text, method = _pdf_text(path), "pdftotext"
    else:
        raise RuntimeError(f"unsupported report format: {suffix or '(none)'}")
    text = html.unescape(text).strip()
    if not text:
        raise RuntimeError(f"{path.name} produced no readable text")
    return ExtractedArtifact(
        path=path, text=text, method=method, sha256=sha256(raw).hexdigest(),
        bytes=len(raw))
