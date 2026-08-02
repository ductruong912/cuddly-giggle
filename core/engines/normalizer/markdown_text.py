"""Find the Markdown an engine produced, and tidy plain-text Markdown.

Engines expose Markdown under half a dozen different keys and sometimes behind a
``.markdown`` attribute, so locating it is its own small concern.
"""
from __future__ import annotations

import re


_MARKDOWN_KEYS = ("markdown", "md", "full_md", "full.markdown", "markdown_texts", "text")


def extract_markdown(raw: dict) -> str | None:
    """Return the first Markdown string found under any known key, recursively."""
    for key in _MARKDOWN_KEYS:
        if key in raw:
            value = raw[key]
            if isinstance(value, str):
                return value
            if isinstance(value, dict):
                nested = extract_markdown(value)
                if nested:
                    return nested
    return None


def result_to_markdown_text(raw: object) -> str | None:
    """Read Markdown from a dict payload or from a result object's ``.markdown``."""
    if isinstance(raw, dict):
        md = extract_markdown(raw)
        if md:
            return md
    if hasattr(raw, "markdown"):
        markdown_attr = getattr(raw, "markdown")
        try:
            value = markdown_attr() if callable(markdown_attr) else markdown_attr
        except Exception:
            value = None
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            md = extract_markdown(value)
            if md:
                return md
    return None


def _starts_with_text_page_marker(line: str) -> bool:
    return bool(
        re.match(r"^(?:#{1,6}\s*)?\[(?:Tr\.|Page)\s*\d+\s*\]\s*:?", line.strip())
    )


def _is_standalone_text_page_marker(line: str) -> bool:
    return bool(
        re.match(r"^(?:#{1,6}\s*)?\[(?:Tr\.|Page)\s*\d+\s*\]\s*:?\s*$", line.strip())
    )


def _text_only_markdown_needs_blank_before(line: str, previous_line: str) -> bool:
    line = line.strip()
    previous_line = previous_line.strip()

    if _starts_with_text_page_marker(line):
        return True
    if _is_standalone_text_page_marker(previous_line):
        return False
    if previous_line.startswith("#"):
        return True
    if re.match(r"^Ngày\b", line, flags=re.IGNORECASE):
        return True
    return line.startswith(("Người dịch:", "Hiệu đính:", "VIỆN ", "VIỆN NGHIÊN"))


def compact_text_only_markdown(markdown: str | None) -> str | None:
    """Drop stray blank lines from prose Markdown, reinserting them where they help.

    Structured Markdown (tables, fenced code) is returned untouched: its blank
    lines are significant.
    """
    if markdown is None:
        return None

    text = markdown.strip()
    if not text:
        return None

    # Structured markdown carries meaningful blank lines for tables/code blocks.
    if any(marker in text for marker in ("<table", "```")) or re.search(r"^\s*\|.*\|\s*$", text, re.MULTILINE):
        return text

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None

    compacted = [lines[0]]
    for line in lines[1:]:
        previous_line = compacted[-1]
        if _text_only_markdown_needs_blank_before(line, previous_line):
            compacted.extend(["", line])
        else:
            compacted.append(line)
    return "\n".join(compacted)
