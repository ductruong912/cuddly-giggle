-- Extraction history: one row per processed document, plus its line items.
--
-- Line items are relational rather than JSON-only so they can be queried
-- ("every order containing TX703AR"), and money columns are NUMERIC rather than
-- double precision — binary floats cannot represent decimal currency exactly.

CREATE TABLE IF NOT EXISTS extractions (
    id                BIGSERIAL   PRIMARY KEY,
    request_id        TEXT        NOT NULL UNIQUE,
    source_filename   TEXT        NOT NULL,
    route             TEXT        NOT NULL,
    engine            TEXT,
    page_count        INTEGER     NOT NULL DEFAULT 0,
    -- Denormalised from `data` so the common lookups need no JSON traversal.
    po_number         TEXT,
    po_date           DATE,
    validation_status TEXT        NOT NULL,
    attempts          INTEGER     NOT NULL DEFAULT 1,
    healed            BOOLEAN     NOT NULL DEFAULT FALSE,
    data              JSONB       NOT NULL,
    issues            JSONB       NOT NULL DEFAULT '[]'::JSONB,
    markdown          TEXT,
    duration_ms       INTEGER,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS extractions_po_number_idx  ON extractions (po_number);
CREATE INDEX IF NOT EXISTS extractions_created_at_idx ON extractions (created_at DESC);
-- Partial: the review queue only ever asks for the rows that failed.
CREATE INDEX IF NOT EXISTS extractions_needs_review_idx
    ON extractions (created_at DESC)
    WHERE validation_status <> 'valid';

CREATE TABLE IF NOT EXISTS extraction_items (
    id              BIGSERIAL PRIMARY KEY,
    extraction_id   BIGINT       NOT NULL REFERENCES extractions (id) ON DELETE CASCADE,
    line_number     INTEGER      NOT NULL,
    toto_number     TEXT         NOT NULL,
    customer_number TEXT,
    quantity        NUMERIC(18, 4) NOT NULL,
    unit_price      NUMERIC(18, 4) NOT NULL,
    extension       NUMERIC(18, 4),
    UNIQUE (extraction_id, line_number)
);

CREATE INDEX IF NOT EXISTS extraction_items_toto_number_idx ON extraction_items (toto_number);
CREATE INDEX IF NOT EXISTS extraction_items_extraction_idx  ON extraction_items (extraction_id);
