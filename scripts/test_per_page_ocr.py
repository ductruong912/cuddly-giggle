"""Standalone test: rasterize a PDF to per-page PNGs and OCR each image alone.

Validates whether processing a PDF page-by-page (as separate images) reads dense
title blocks more reliably than handing the whole PDF to PaddleOCR.

Usage:
    python -m scripts.test_per_page_ocr "data_test/2.Bản vẽ xuất từ file gốc.pdf" --dpi 300
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Ensure repo root is importable when run as a script.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import settings
from app.services.engines.registry import create_engine


def rasterize_pdf(pdf_path: Path, out_dir: Path, dpi: int) -> list[Path]:
    import fitz  # PyMuPDF

    out_dir.mkdir(parents=True, exist_ok=True)
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    image_paths: list[Path] = []
    doc = fitz.open(str(pdf_path))
    try:
        for page_index, page in enumerate(doc):
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img_path = out_dir / f"{pdf_path.stem}_p{page_index + 1}.png"
            pix.save(str(img_path))
            image_paths.append(img_path)
            print(f"  rendered page {page_index + 1}: {pix.width}x{pix.height}px -> {img_path}")
    finally:
        doc.close()
    return image_paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", help="Path to the input PDF")
    parser.add_argument("--dpi", type=int, default=300, help="Rasterization DPI (default: 300)")
    parser.add_argument("--engine", default=settings.primary_engine, help="OCR engine name")
    parser.add_argument("--out-dir", default="outputs/per_page_test", help="Output folder")
    args = parser.parse_args()

    pdf_path = Path(args.pdf).resolve()
    out_dir = Path(args.out_dir).resolve()
    if not pdf_path.is_file():
        raise SystemExit(f"PDF not found: {pdf_path}")

    print(f"Rasterizing {pdf_path.name} at {args.dpi} DPI ...")
    image_paths = rasterize_pdf(pdf_path, out_dir, args.dpi)

    print(f"Creating engine '{args.engine}' ...")
    engine = create_engine(args.engine, settings)

    for image_path in image_paths:
        print(f"\n=== OCR {image_path.name} ===")
        result = engine.parse(str(image_path))
        md_path = image_path.with_suffix(".md")
        markdown = result.markdown or ""
        md_path.write_text(markdown, encoding="utf-8")
        print(f"  pages={len(result.pages)} markdown_chars={len(markdown)} -> {md_path}")


if __name__ == "__main__":
    main()
