from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from rapidfuzz import fuzz

from app.domain.schemas import Block, Table


@dataclass(frozen=True)
class NormalizationRule:
    src: str
    dst: str


COMMON_VIETNAMESE_FIXES = [
    NormalizationRule("\u00f2a", "o\u00e0"),
    NormalizationRule("\u00f3a", "o\u00e1"),
    NormalizationRule("\u1ecfa", "o\u1ea3"),
    NormalizationRule("\u00f5a", "o\u00e3"),
    NormalizationRule("\u1ecda", "o\u1ea1"),
    NormalizationRule("\u00f2e", "o\u00e8"),
    NormalizationRule("\u00f3e", "o\u00e9"),
    NormalizationRule("\u1ecfe", "o\u1ebb"),
    NormalizationRule("\u00f5e", "o\u1ebd"),
    NormalizationRule("\u1ecde", "o\u1eb9"),
    NormalizationRule("\u00f9y", "u\u1ef3"),
    NormalizationRule("\u00fay", "u\u00fd"),
    NormalizationRule("\u1ee7y", "u\u1ef7"),
    NormalizationRule("\u0169y", "u\u1ef9"),
    NormalizationRule("\u1ee5y", "u\u1ef5"),
]


DOMAIN_DICTIONARY = [
    "C\u1ed9ng h\u00f2a x\u00e3 h\u1ed9i ch\u1ee7 ngh\u0129a Vi\u1ec7t Nam",
    "\u0110\u1ed9c l\u1eadp - T\u1ef1 do - H\u1ea1nh ph\u00fac",
    "h\u00f3a \u0111\u01a1n",
    "bi\u00ean b\u1ea3n",
    "m\u00e3 s\u1ed1 thu\u1ebf",
    "ng\u00e0y",
    "th\u00e1ng",
    "n\u0103m",
]


VIETNAMESE_PHRASE_RESTORES = [
    (r"\bNHA CUNG CAP\b", "NH\u00c0 CUNG C\u1ea4P"),
    (r"\bLUU Y\b", "L\u01afU \u00dd"),
    (r"\bNEU CO\b", "N\u1ebeU C\u00d3"),
    (r"\bBAT KY\b", "B\u1ea4T K\u1ef2"),
    (r"\bSAI BIET\b", "SAI BI\u1ec6T"),
    (r"\bGIA MUA\b", "GI\u00c1 MUA"),
    (r"\bQUY CACH\b", "QUY C\u00c1CH"),
    (r"\bDAT HANG\b", "\u0110\u1eb6T H\u00c0NG"),
    (r"\bDIEU CHINH\b", "\u0110I\u1ec0U CH\u1ec8NH"),
    (r"\bVOI\b", "V\u1edaI"),
    (r"\bTRUNG TAM\b", "TRUNG T\u00c2M"),
    (r"\bTRUOC KHI\b", "TR\u01af\u1edaC KHI"),
    (r"\bGIAO HANG\b", "GIAO H\u00c0NG"),
    (r"\bPHAN PHOI TIEN TIEN\b", "PH\u00c2N PH\u1ed0I TI\u00caN TI\u1ebeN"),
    (r"\bDUONG PHAN DANG LUU\b", "\u0110\u01af\u1edcNG PHAN \u0110\u0102NG L\u01afU"),
    (r"\bPHUONG TAN SON HOA\b", "PH\u01af\u1edcNG T\u00c2N S\u01a0N H\u00d2A"),
    (r"\bPHUONG HUNG PHU\b", "PH\u01af\u1edcNG H\u01afNG PH\u00da"),
    (r"\bPHUONG CAU KIEU\b", "PH\u01af\u1edcNG C\u1ea6U KI\u1ec6U"),
    (r"\bPHO QUANG\b", "PH\u1ed4 QUANG"),
    (r"\bHO CHI MINH\b", "H\u1ed2 CH\u00cd MINH"),
    (r"\bCAN THO\b", "C\u1ea6N TH\u01a0"),
    (r"\bVIET NAM\b", "VI\u1ec6T NAM"),
    (r"\bVietnam\b", "Vi\u1ec7t Nam"),
    (r"\bSO\s+(\d+)", "S\u1ed0 \\1"),
    (r"\bNcc\b", "NCC"),
    (r"\bLuu Y\b", "L\u01b0u \u00dd"),
    (r"\bvui long\b", "vui l\u00f2ng"),
    (r"\bgiao hang\b", "giao h\u00e0ng"),
    (r"\bxu\u1ea5t hoa don\b", "xu\u1ea5t h\u00f3a \u0111\u01a1n"),
    (r"\bxuat hoa don\b", "xu\u1ea5t h\u00f3a \u0111\u01a1n"),
    (r"\bhoa don\b", "h\u00f3a \u0111\u01a1n"),
    (r"\btung don hang\b", "t\u1eebng \u0111\u01a1n h\u00e0ng"),
    (r"\btung nhom hang\b", "t\u1eebng nh\u00f3m h\u00e0ng"),
    (r"\bdon hang\b", "\u0111\u01a1n h\u00e0ng"),
    (r"\bnhom hang\b", "nh\u00f3m h\u00e0ng"),
    (r"\bva\b", "v\u00e0"),
    (r"\bCai\b", "C\u00e1i"),
]


MOJIBAKE_MARKERS = ("Ã", "Â", "Ä", "Å", "áº", "á»", "VNÄ")


def _repair_mojibake(text: str) -> str:
    if not text or not any(marker in text for marker in MOJIBAKE_MARKERS):
        return text
    try:
        repaired = text.encode("latin1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    if repaired.count("\ufffd") > text.count("\ufffd"):
        return text
    return repaired


def _restore_vietnamese_phrases(text: str) -> str:
    restored = text
    for pattern, replacement in VIETNAMESE_PHRASE_RESTORES:
        restored = re.sub(pattern, replacement, restored)
    return restored


def _normalize_text(text: str) -> str:
    normalized = _repair_mojibake(text)
    normalized = unicodedata.normalize("NFC", normalized)
    normalized = re.sub(r"[ \t]+", " ", normalized)
    for rule in COMMON_VIETNAMESE_FIXES:
        normalized = normalized.replace(rule.src, rule.dst)
    normalized = _restore_vietnamese_phrases(normalized)
    return normalized.strip()


def _dictionary_fix(token: str) -> str:
    cleaned = token.strip()
    if not cleaned:
        return cleaned

    best = cleaned
    best_score = 0.0
    for keyword in DOMAIN_DICTIONARY:
        score = fuzz.ratio(cleaned.lower(), keyword.lower())
        if score > best_score:
            best_score = score
            best = keyword
    if best_score >= 92:
        return best
    return cleaned


def _normalize_numeric_text(text: str) -> str:
    text = re.sub(r"\s*(VND|VN\u0110|USD|EUR)\b", r" \1", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(\d{1,2})[.\-](\d{1,2})[.\-](\d{2,4})\b", r"\1/\2/\3", text)
    text = re.sub(r"\b([A-Z]{2,5})\s+(\d{4,})\b", lambda m: f"{m.group(1).upper()} {m.group(2)}", text)
    return text


def postprocess_blocks(blocks: list[Block]) -> list[Block]:
    processed: list[Block] = []
    for block in blocks:
        content = _normalize_text(block.content)
        content = _normalize_numeric_text(content)
        if len(content.split()) <= 8:
            content = _dictionary_fix(content)
        processed.append(block.model_copy(update={"content": content}))
    return processed


def postprocess_tables(tables: list[Table]) -> list[Table]:
    processed: list[Table] = []
    for table in tables:
        cells = []
        for cell in table.cells:
            text = _normalize_text(cell.text)
            text = _normalize_numeric_text(text)
            cells.append(cell.model_copy(update={"text": text}))
        processed.append(table.model_copy(update={"cells": cells}))
    return processed


def postprocess_markdown(markdown: str | None) -> str | None:
    if markdown is None:
        return None
    return _normalize_numeric_text(_normalize_text(markdown))
