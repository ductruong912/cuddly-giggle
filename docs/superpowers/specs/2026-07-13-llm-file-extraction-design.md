# LLM file extraction API — Design

## Goal

Add an API that accepts an uploaded document, runs the existing in-process OCR
pipeline, then uses OpenAI `gpt-5-mini` to extract user-defined structured
data. It returns JSON. The existing `POST /v1/doc/parse` endpoint, its
Markdown response, and its artifact-writing behavior remain unchanged.

## Scope

- Reuse `ParseOrchestrator` directly; do not make an HTTP request to
  `/v1/doc/parse`.
- Support the same file formats and OCR fallback behavior as the parse API.
- Make extraction instructions and the output JSON Schema editable in one
  prompt module.
- Use OpenAI Responses API Structured Outputs in strict schema mode.
- Provide synchronous request/response behavior suitable for the current
  synchronous FastAPI routes.

Out of scope for the first version: persisted jobs, asynchronous processing,
per-tenant prompt selection, chunk-and-merge extraction for oversized files,
and a UI for editing prompts.

## API contract

### Endpoint

`POST /v1/llm/extract`

Request: `multipart/form-data` with required `file` field. File validation
uses the same allow-list as `/v1/doc/parse`.

Success response: `application/json`.

```json
{
  "request_id": "req_ab12cd34ef56",
  "ocr": {
    "decision": "Parse completed.",
    "page_count": 1
  },
  "data": {
    "document_type": "invoice",
    "fields": [],
    "items": []
  }
}
```

`data` is exactly the object produced under the JSON Schema defined in
`app/prompts/prompt.py`. The envelope is stable; the contents of `data` are
intentionally domain-specific and customizable.

Errors:

- `400`: unsupported file extension.
- `413`: OCR input/context is larger than configured limits.
- `422`: the model refuses the request or produces no usable structured
  result.
- `503`: OCR service unavailable or transient OpenAI failure after retries.
- `500`: unexpected internal failure.

## Components and responsibilities

### `app/api/routes.py`

Add `llm_router` with `POST /v1/llm/extract`. The handler follows the proven
temporary-upload lifecycle of `parse_document`: validate suffix, write a UUID
temporary file, call the injected `ParseOrchestrator`, call the extraction
service, and remove the temporary file in `finally`. It does not call
`save_parse_artifacts`.

The route receives `ParseOrchestrator` through the existing `get_orchestrator`
dependency, so OCR engine instances are shared and no HTTP hop or duplicate OCR
routing is introduced. It receives an `LLMExtractionService` through a new
cached dependency to make API tests replaceable.

### `app/services/llm_extraction.py`

Define `LLMExtractionService` with a single public operation:

```python
extract(parse_response: ParseResponse) -> dict[str, Any]
```

It:

1. Builds a compact, labelled document context from OCR Markdown. Include
   tables in document order when they are not represented reliably in Markdown.
2. Enforces configured character/token-safe limits before an external request.
3. Calls the OpenAI Python SDK Responses API with `gpt-5-mini`, developer
   instructions and `text.format` JSON Schema in strict mode.
4. Detects refusals and incomplete responses, parses the returned JSON, and
   validates it against the configured schema before returning it.
5. Maps retryable provider errors (timeouts, rate limits and 5xx) to a bounded
   retry policy with exponential backoff; never retries refusal or schema
   errors.

OCR text is untrusted document content. Instructions explicitly state that it
is source material, never instructions to follow, and require missing values to
be returned as the schema's allowed null/empty form rather than invented.

### `app/prompts/prompt.py`

This is the user-editable extraction contract. It exports:

- `EXTRACTION_INSTRUCTIONS`: Vietnamese/English domain extraction rules.
- `EXTRACTION_SCHEMA_NAME`: stable, API-safe schema name.
- `EXTRACTION_JSON_SCHEMA`: strict JSON Schema for `data`.

The initial example is generic and uses `document_type`, `fields`, and `items`.
Users customise both the instructions and schema for invoices, contracts, forms,
or other document types. Every property needed in strict mode must be declared
and required; optional semantics use nullable types or empty arrays.

### Configuration

Add settings, documented in `.env.example`:

- `OPENAI_API_KEY` (required only by the new endpoint; never logged)
- `OPENAI_MODEL` defaulting to `gpt-5-mini`
- `OPENAI_TIMEOUT_SECONDS`
- `OPENAI_MAX_RETRIES`
- `LLM_MAX_INPUT_CHARS`

Add the official `openai` Python package to `requirements.txt`. Existing OCR
and llama.cpp configuration are unchanged.

### Domain schemas

Add Pydantic response models for the stable outer response and OCR metadata.
`data` remains `dict[str, Any]` because its final shape lives in
`app/prompts/prompt.py`; the extraction service enforces that specific schema.

## Data flow

```text
uploaded file
  -> temporary file
  -> ParseOrchestrator.parse()
  -> ParseResponse (Markdown, pages, tables)
  -> context builder + prompt.py schema
  -> OpenAI Responses API / gpt-5-mini
  -> schema validation
  -> stable JSON envelope
```

## Observability and privacy

Log request ID, file suffix, OCR duration, LLM duration, model, retry count,
input length, output length and token usage when supplied by the provider. Do
not log API keys, authorization headers, complete OCR text or extracted
personal data. The route returns the generated data only to the caller.

## Testing and acceptance criteria

Tests use fake OCR and fake OpenAI clients; no GPU and no network calls are
required.

- Existing `/v1/doc/parse` tests stay green and keep returning Markdown.
- The new endpoint accepts a supported file, calls the injected orchestrator,
  and returns a JSON envelope containing validated `data`.
- Unsupported files return 400 and OCR is not called.
- Empty OCR Markdown, context over the limit, refusal, malformed output,
  timeout and retry exhaustion produce the intended HTTP error without leaking
  secrets.
- Tests prove the prompt module's schema is passed to the client and invalid
  output is rejected before it reaches the route response.
- A small fixture set of representative documents and expected JSON is added
  later for regression/evaluation whenever the prompt is tuned.
