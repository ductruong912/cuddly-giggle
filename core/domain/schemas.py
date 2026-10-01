from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


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
    source_engine: str = ""


class ParseDecision(BaseModel):
    reason: str


class ParseResponse(BaseModel):
    request_id: str
    decision: ParseDecision
    pages: list[PageParseResult]
    blocks: list[Block]
    tables: list[Table]
    reading_order: list[str]
    markdown: str | None = None
    engine_name: str = ""


class LLMExtractionOCRMetadata(BaseModel):
    decision: str
    page_count: int


class ValidationIssue(BaseModel):
    """One deterministic check that the extracted record failed."""

    field: str
    message: str
    severity: str


class ExtractionValidation(BaseModel):
    """Whether the extracted record reconciles, and what the retry loop did.

    ``status`` is ``needs_review`` when the record still fails a blocking check
    after the self-heal retries are exhausted. The data is still returned, so a
    caller can decide whether to route it to a human.
    """

    status: str
    attempts: int
    healed: bool
    issues: list[ValidationIssue] = Field(default_factory=list)


class LLMExtractionResponse(BaseModel):
    request_id: str
    ocr: LLMExtractionOCRMetadata
    data: dict[str, Any]
    validation: ExtractionValidation
