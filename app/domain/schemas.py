from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class LangHint(str, Enum):
    vi = "vi"
    auto = "auto"


class BlockType(str, Enum):
    text = "text"
    table = "table"
    formula = "formula"
    chart = "chart"
    seal = "seal"
    title = "title"
    other = "other"


class Point(BaseModel):
    x: float
    y: float


class Block(BaseModel):
    block_id: str
    type: BlockType
    content: str = ""
    bbox: list[Point] = Field(default_factory=list)
    confidence: float = 0.0
    page_index: int = 0
    source_engine: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)


class TableCell(BaseModel):
    row: int
    col: int
    rowspan: int = 1
    colspan: int = 1
    text: str = ""
    confidence: float = 0.0


class Table(BaseModel):
    table_id: str
    page_index: int
    cells: list[TableCell] = Field(default_factory=list)
    confidence: float = 0.0


class PageParseResult(BaseModel):
    page_index: int
    blocks: list[Block] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    reading_order: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    quality_score: float = 0.0
    source_engine: str = ""


class QualityFlags(BaseModel):
    skew: bool = False
    blur: bool = False
    illumination_issue: bool = False
    screen_photo: bool = False
    low_resolution: bool = False


class ParseDecision(BaseModel):
    status: Literal["pass", "borderline", "fail"]
    reason: str


class ParseResponse(BaseModel):
    request_id: str
    decision: ParseDecision
    pages: list[PageParseResult]
    blocks: list[Block]
    tables: list[Table]
    reading_order: list[str]
    quality_flags: QualityFlags
    markdown: str | None = None
    review_queued: bool = False
    review_reason: str | None = None
    saved_files: list[str] = Field(default_factory=list)


class ParseOptions(BaseModel):
    lang_hint: LangHint = LangHint.auto
    enable_fallback: bool = True
