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


class CoordinateSpace(str, Enum):
    processed_image_pixels = "processed_image_pixels"
    pdf_points = "pdf_points"
    none = "none"


class PageGeometry(BaseModel):
    width: float = 0.0
    height: float = 0.0
    coordinate_space: CoordinateSpace = CoordinateSpace.none


class ConfidenceSource(str, Enum):
    real_engine = "real_engine"
    synthesized = "synthesized"
    unknown = "unknown"


class Block(BaseModel):
    block_id: str
    type: BlockType
    content: str = ""
    bbox: list[Point] = Field(default_factory=list)
    confidence: float = 0.0
    confidence_source: ConfidenceSource = ConfidenceSource.unknown
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


class PageVisualDTO(BaseModel):
    available: bool = False
    kind: str | None = None
    url: str | None = None


class PageParseResult(BaseModel):
    page_index: int
    geometry: PageGeometry = Field(default_factory=PageGeometry)
    blocks: list[Block] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    reading_order: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    source_engine: str = ""
    visual: PageVisualDTO = Field(default_factory=PageVisualDTO)


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


class ParseBlockDTO(BaseModel):
    block_id: str
    type: BlockType
    content: str = ""
    confidence: float = 0.0
    confidence_source: ConfidenceSource = ConfidenceSource.unknown
    bbox: list[Point] = Field(default_factory=list)
    bbox_normalized: list[Point] = Field(default_factory=list)
    page_index: int = 0
    source_engine: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)


class ParsePageDTO(BaseModel):
    page_index: int
    geometry: PageGeometry
    blocks: list[ParseBlockDTO] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    reading_order: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    visual: PageVisualDTO = Field(default_factory=PageVisualDTO)


class DocumentParseResponse(BaseModel):
    request_id: str
    decision: ParseDecision
    engine_name: str = ""
    markdown: str | None = None
    pages: list[ParsePageDTO] = Field(default_factory=list)


def to_document_parse_response(response: ParseResponse) -> DocumentParseResponse:
    """Chuyển đổi ParseResponse nội bộ sang DTO chuẩn hóa cho API /v1/doc/parse."""
    parsed_pages: list[ParsePageDTO] = []
    for page in response.pages:
        geom = page.geometry
        w = geom.width
        h = geom.height

        parsed_blocks: list[ParseBlockDTO] = []
        for block in page.blocks:
            bbox_norm: list[Point] = []
            if w > 0 and h > 0 and block.bbox:
                bbox_norm = [
                    Point(
                        x=round(max(0.0, min(1.0, pt.x / w)), 4),
                        y=round(max(0.0, min(1.0, pt.y / h)), 4),
                    )
                    for pt in block.bbox
                ]

            conf_source = block.confidence_source
            if conf_source == ConfidenceSource.unknown:
                if block.source_engine in {"pdf_text", "word_text", "excel_text"}:
                    conf_source = ConfidenceSource.synthesized
                elif block.confidence > 0.0:
                    conf_source = ConfidenceSource.real_engine

            parsed_blocks.append(
                ParseBlockDTO(
                    block_id=block.block_id,
                    type=block.type,
                    content=block.content,
                    confidence=block.confidence,
                    confidence_source=conf_source,
                    bbox=block.bbox,
                    bbox_normalized=bbox_norm,
                    page_index=block.page_index,
                    source_engine=block.source_engine,
                    extra=block.extra,
                )
            )

        visual = page.visual.model_copy()
        if visual.available and not visual.url:
            visual.url = f"/v1/doc/parse/{response.request_id}/pages/{page.page_index}/image"

        parsed_pages.append(
            ParsePageDTO(
                page_index=page.page_index,
                geometry=geom,
                blocks=parsed_blocks,
                tables=page.tables,
                reading_order=page.reading_order,
                confidence=page.confidence,
                visual=visual,
            )
        )

    return DocumentParseResponse(
        request_id=response.request_id,
        decision=response.decision,
        engine_name=response.engine_name,
        markdown=response.markdown,
        pages=parsed_pages,
    )


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
