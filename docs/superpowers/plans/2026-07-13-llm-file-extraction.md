# LLM File Extraction API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a file-upload API that runs existing OCR and returns a configurable GPT-5 mini extraction JSON response without changing `/v1/doc/parse`.

**Architecture:** `POST /v1/llm/extract` reuses the in-process `ParseOrchestrator`; it passes normalized Markdown to an injected `LLMExtractionService`. The service obtains instructions and a strict JSON Schema from `app/prompts/prompt.py`, calls the OpenAI Responses API, and returns validated JSON in a stable response envelope.

**Tech Stack:** Python, FastAPI, Pydantic v2, OpenAI Python SDK, pytest.

## Global Constraints

- Preserve the existing `/v1/doc/parse` response contract.
- Never make an HTTP call from the new route to `/v1/doc/parse`.
- Keep user-editable instructions and JSON Schema in `app/prompts/prompt.py`.
- Default to `OPENAI_MODEL=gpt-5-mini`; load the key from `OPENAI_API_KEY`.
- Never log a key or complete document/OCR content.
- Use TDD: each production behavior follows a test that has been observed failing.

---

### Task 1: Add prompt contract and extraction service

**Files:**

- Create: `app/prompts/__init__.py`
- Create: `app/prompts/prompt.py`
- Create: `app/services/llm_extraction.py`
- Create: `tests/test_llm_extraction.py`
- Modify: `app/core/config.py`, `requirements.txt`, `.env.example`

**Interfaces:** Produces `LLMExtractionService.extract(parse_response: ParseResponse) -> dict[str, Any]`, `LLMExtractionError`, and a prompt module exporting `EXTRACTION_INSTRUCTIONS`, `EXTRACTION_SCHEMA_NAME`, and `EXTRACTION_JSON_SCHEMA`.

- [ ] **Step 1: Write failing behavior tests**

```python
def test_extract_uses_prompt_schema_and_returns_json(make_parse_response):
    client = FakeResponsesClient('{"document_type":"invoice","fields":[],"items":[]}')
    result = LLMExtractionService(client=client, app_settings=make_settings()).extract(make_parse_response("Invoice 1"))
    assert result["document_type"] == "invoice"
    assert client.calls[0]["text"]["format"]["schema"] == EXTRACTION_JSON_SCHEMA

def test_extract_rejects_empty_ocr_content(make_parse_response):
    with pytest.raises(LLMExtractionError, match="OCR produced no usable text"):
        LLMExtractionService(FakeResponsesClient("{}"), make_settings()).extract(make_parse_response(None))
```

- [ ] **Step 2: Verify RED**

Run `./venv/Scripts/python -m pytest tests/test_llm_extraction.py -v`.

Expected: collection fails because `app.services.llm_extraction` does not exist.

- [ ] **Step 3: Implement the smallest service and configuration**

```python
class LLMExtractionService:
    def extract(self, parse_response: ParseResponse) -> dict[str, Any]:
        markdown = (parse_response.markdown or "").strip()
        if not markdown:
            raise LLMExtractionError("OCR produced no usable text")
        response = self.client.responses.create(
            model=self.settings.openai_model,
            instructions=EXTRACTION_INSTRUCTIONS,
            input=markdown,
            text={"format": {"type": "json_schema", "name": EXTRACTION_SCHEMA_NAME,
                              "strict": True, "schema": EXTRACTION_JSON_SCHEMA}},
        )
        return json.loads(response.output_text)
```

Add `openai`, settings for API key/model/timeout/retries/max input chars, and corresponding `.env.example` entries. `prompt.py` starts with a generic strict schema containing `document_type`, `fields`, and `items`.

- [ ] **Step 4: Verify GREEN**

Run `./venv/Scripts/python -m pytest tests/test_llm_extraction.py -v`.

Expected: PASS.

- [ ] **Step 5: Commit**

Run `git add app/prompts app/services/llm_extraction.py app/core/config.py requirements.txt .env.example tests/test_llm_extraction.py` then `git commit -m "feat: add configurable LLM extraction service"`.

### Task 2: Add independent upload route

**Files:**

- Modify: `app/domain/schemas.py`, `app/api/routes.py`, `app/api/application.py`
- Create: `tests/test_llm_api.py`

**Interfaces:** Consumes `LLMExtractionService.extract(ParseResponse) -> dict[str, Any]`. Produces `POST /v1/llm/extract` returning `LLMExtractionResponse` with `request_id`, OCR metadata and `data: dict[str, Any]`.

- [ ] **Step 1: Write failing API tests**

```python
def test_llm_extract_returns_structured_data(client):
    response = client.post("/v1/llm/extract", files={"file": ("doc.pdf", b"%PDF", "application/pdf")})
    assert response.status_code == 200
    assert response.json()["data"]["document_type"] == "invoice"

def test_llm_extract_rejects_an_unsupported_file(client):
    response = client.post("/v1/llm/extract", files={"file": ("note.txt", b"x", "text/plain")})
    assert response.status_code == 400
```

- [ ] **Step 2: Verify RED**

Run `./venv/Scripts/python -m pytest tests/test_llm_api.py -v`.

Expected: first test fails with 404.

- [ ] **Step 3: Implement the route with dependency injection**

```python
llm_router = APIRouter(prefix="/v1/llm", tags=["llm"])

@llm_router.post("/extract", response_model=LLMExtractionResponse)
def extract_document(file: UploadFile = File(...),
                     orchestrator: ParseOrchestrator = Depends(get_orchestrator),
                     extractor: LLMExtractionService = Depends(get_llm_extractor)):
    # validate file, write UUID temporary file, call orchestrator then extractor,
    # map known errors, and unlink the temporary file in finally
```

Use the parse route's suffix allow-list and temporary-file lifecycle, but do not call `save_parse_artifacts`. Register `llm_router` in the app factory.

- [ ] **Step 4: Verify GREEN and preservation**

Run `./venv/Scripts/python -m pytest tests/test_llm_api.py tests/test_api.py -v`.

Expected: PASS; parse API tests remain Markdown responses.

- [ ] **Step 5: Commit**

Run `git add app/domain/schemas.py app/api/routes.py app/api/application.py tests/test_llm_api.py` then `git commit -m "feat: add LLM file extraction endpoint"`.

### Task 3: Add failure handling and documentation

**Files:**

- Modify: `app/services/llm_extraction.py`, `app/api/routes.py`, `tests/test_llm_extraction.py`, `tests/test_llm_api.py`, `README.md`

**Interfaces:** Adds concrete errors mapped to 413 (input limit), 422 (refusal or malformed result), and 503 (provider unavailable).

- [ ] **Step 1: Write failing error-path tests**

```python
def test_extract_rejects_context_over_configured_limit(make_parse_response):
    service = LLMExtractionService(FakeResponsesClient("{}"), make_settings(max_chars=3))
    with pytest.raises(LLMExtractionInputTooLarge):
        service.extract(make_parse_response("four"))

def test_llm_extract_returns_503_for_provider_failure(client):
    client.override_extractor(UnavailableExtractor())
    response = client.post("/v1/llm/extract", files={"file": ("doc.pdf", b"%PDF", "application/pdf")})
    assert response.status_code == 503
```

- [ ] **Step 2: Verify RED**

Run `./venv/Scripts/python -m pytest tests/test_llm_extraction.py tests/test_llm_api.py -v`.

Expected: FAIL because input limit and provider mapping do not yet exist.

- [ ] **Step 3: Implement bounded failures and docs**

```python
if len(markdown) > self.settings.llm_max_input_chars:
    raise LLMExtractionInputTooLarge("OCR text exceeds configured input limit")
try:
    response = self.client.responses.create(...)
except (APITimeoutError, RateLimitError, APIConnectionError) as exc:
    raise LLMExtractionUnavailable("OpenAI extraction is temporarily unavailable") from exc
```

Map errors in the route, add concise README setup/curl examples, and explain that `app/prompts/prompt.py` owns customization.

- [ ] **Step 4: Verify full regression suite**

Run `./venv/Scripts/python -m pytest -q`.

Expected: all tests PASS.

- [ ] **Step 5: Commit**

Run `git add app/services/llm_extraction.py app/api/routes.py tests/test_llm_extraction.py tests/test_llm_api.py README.md` then `git commit -m "feat: harden LLM extraction errors"`.

## Self-review

- Spec coverage: Tasks 1–3 cover configurable prompt/schema, direct OCR reuse, stable response, configuration, structured output, failure behavior, observability constraints, docs, and tests.
- Placeholder scan: no undecided API names or missing interfaces remain; implementation snippets specify the concrete public operations.
- Type consistency: the service accepts `ParseResponse` and returns `dict[str, Any]`; the route wraps that value as `LLMExtractionResponse.data`.
