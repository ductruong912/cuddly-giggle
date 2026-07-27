# INSTRUCTIONS.md
## Binding rules for AI coding agents on this project

## 1. Architecture
- Strict OOP: stateful/multi-step logic → classes. Plain functions only for small, pure, stateless helpers.
- DRY: search existing code before writing new logic. No copy-paste duplication.
- No monolithic files. One concern per file. Split any file exceeding ~300-400 lines.
- No over-engineering: add a pattern/abstraction only if a concrete current need exists — not a hypothetical one. Prefer the simplest OOP design that works.
- Type hints + docstrings on all public methods. No magic numbers, no vague names (`x`, `tmp`, `data2`).
- Follow existing project patterns; don't introduce competing styles without flagging why.

## 2. File Structure
project_root/
├── venv/
├── config/settings.py          # env vars, constants, config loading
├── models/<entity>.py          # data classes, validation only
├── services/<name>_service.py  # business logic, external calls, I/O
├── utils/<name>utils.py        # pure, stateless helpers only
├── tests/test<module>.py
├── logs/
├── main.py                     # orchestration only, no business logic
├── requirements.txt
├── .env.example
└── .gitignore

- One primary class per file, matching filename (`invoice_service.py` → `InvoiceService`).
- `__init__` only assigns dependencies — no I/O or heavy compute.
- Composition over inheritance.

## 3. Virtual Environment
- Always named `venv`. Never `.venv`, `env`, conda, etc.
- Create: `python -m venv venv`
- Activate: `source venv/bin/activate` (Mac/Linux) | `venv\Scripts\Activate.ps1` (PowerShell)
- Upgrade: `python -m pip install --upgrade pip`
- Install: `pip install -r requirements.txt` (never global pip)
- Pin new deps in `requirements.txt`.
- `.gitignore` must include: `venv/`, `__pycache__/`, `*.pyc`, `.env`, `logs/`

## 4. Logging
- `print()` banned for debugging/status — only for intentional CLI user-output.
- Every module: `logger = logging.getLogger(__name__)`. Config centralized once in `main.py`/`config/`.
- Levels: `DEBUG` = internals/variable states; `INFO` = milestones (start/end, batch counts); `WARNING` = recoverable issue; `ERROR` = failed operation, app continues; `CRITICAL` = app must exit.
- Log entry/exit of non-trivial methods (I/O, API calls, transforms).
- Every `except` block must `logger.exception(...)` — no bare `except: pass`.
- Never log secrets/PII (mask tokens: `token[:4]+"***"`).

## 5. Performance & Resources
- Use `with` for all closable resources (files, sockets, DB/HTTP clients). No manual open/close.
- Avoid O(n²)+ loops when hashing/indexing/vectorization can achieve linear time.
- Batch external calls (bulk DB writes, paginated API calls) instead of per-record calls.
- Reuse connections/sessions/clients across calls — instantiate once.
- Use generators/streaming for large data instead of loading everything into memory.
- Don't add caching layers or micro-optimizations without real scale justifying it.

## 6. External APIs & Docs
- Before using any third-party lib/API/SDK (esp. cloud SDKs, AI provider APIs, payment/auth), verify current syntax via official docs or web search — don't rely solely on memory.
- Skip re-verification for stable stdlib (`os`, `json`, `pathlib`) or APIs already verified this session.
- Flag breaking changes between dependency versions to the user.
- If verification isn't possible, say so explicitly rather than presenting unverified syntax as fact.

## 7. Pre-Delivery Checklist
- [ ] No monolithic files; logic in correct module
- [ ] Classes used for stateful/complex logic; no duplicated logic (DRY)
- [ ] No unnecessary patterns/abstractions
- [ ] Type hints + docstrings present
- [ ] All fallible operations have specific `try/except` + `logger.exception`
- [ ] No debug `print()`; logging used with correct levels
- [ ] Resources use `with`; no obvious O(n²) or unbatched calls
- [ ] `venv` naming consistent; `requirements.txt` updated
- [ ] Third-party API syntax verified against current docs
- [ ] No leftover `TODO`/stubs — code actually runs