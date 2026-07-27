# Two OCR API design

## Goal

Replace the existing document extraction route names with exactly two OCR entry points.  The replacement is non-compatible: the previous `extract` and `extract-fast` names are removed rather than retained as aliases.

## Public API

The document router exposes these routes:

| Route | Processing path | Accepted files |
| --- | --- | --- |
| `POST /v1/extract/local` | Detect local hardware. Use PaddleOCR-VL when a GPU is available; otherwise use the existing CPU-oriented PaddleOCR v6 engine. | Existing locally supported document and image types. |
| `POST /v1/extract/online` | Submit PDFs and images to DataLab's SuryaOCR service. | PDFs and existing fast-path image types. |

Both endpoints retain the existing extraction response schema and structured-LLM post-processing.  The local route continues to accept the existing Markdown and JSON direct-extraction inputs.  The online route remains a multipart file-upload endpoint because it requires an OCR file input.

## Local routing

Introduce a local OCR selector that determines GPU availability at request/runtime setup time.  It dispatches to `PaddleOCRVLEngine` when a GPU is usable and dispatches to `PaddleOCRFastEngine` (PaddleOCR v6 CPU profile) otherwise.  This decision is automatic; environment settings must not redirect the local endpoint to DataLab.

The existing native text extraction behavior for PDF, Word, and Excel remains in the local orchestrator.  Only its OCR fallback becomes hardware-aware.

## Online routing

The online endpoint owns a dedicated DataLab/SuryaOCR orchestrator.  It always uses `DataLabFastEngine`; it does not fall back to local OCR.  Missing credentials or DataLab errors surface as the existing service-unavailable response rather than silently changing providers.

## Cleanup

Remove the `/v1/doc` route prefix for the replacement API, delete `/extract` and `/extract-fast`, and remove configuration/documentation that represents DataLab as a `FAST_OCR_PROVIDER` selection or fallback.  Rename user-visible fast-ocr terminology to local CPU OCR or online OCR as appropriate.

## Error handling and tests

Preserve current request validation and LLM-extraction error mappings.  Add route-level tests proving that the two published paths dispatch to their intended orchestrators and that old route names are absent.  Add selector tests covering both GPU/VLM and CPU/Paddle v6 choices, plus an online-orchestrator test showing DataLab failures do not fall back locally.
