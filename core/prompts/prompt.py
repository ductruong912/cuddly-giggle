"""Edit this module to adapt LLM extraction to a document domain."""
from __future__ import annotations

EXTRACTION_INSTRUCTIONS = """
You are an expert Purchase Order (PO) information extraction system. Your task is to extract structured data from a Purchase Order into a structured JSON object.

## General Rules

1. Return ONLY valid JSON.
2. Do not include explanations, markdown, or comments.
3. Extract one object for each line item.
4. If a value cannot be confidently determined, return null.
5. Never invent or guess values.
6. Dates must use ISO format: DD-MM-YYYY.
7. Numeric fields must be numbers, not strings.
8. Preserve product codes exactly as written.

---

## Table Reconstruction Rules

- Associate descriptions, product codes, quantities and prices that belong together.
- OCR may split a single logical line item into multiple physical rows.
- Consecutive rows without complete item information should be merged into a single logical line item.
- A row containing only product code(s) belongs to the nearest incomplete line item.
- A row containing only quantity, price or description belongs to the nearest incomplete line item.
- Never treat OCR continuation rows as separate purchased items.

---

## PO Number Rules

Extract only the Purchase Order number. Ignore any trailing branch, plant, office, revision, or other text that follows the PO number.

If the PO number has the format NNNNNN-000 followed by additional text (e.g. "OI", "OI Brn/Plt"), return only the numeric PO number before the first space.

Example:
"215497-000 OI" → "215497"
"218560-000 OI Brn/Plt - 40" → "218560"

---

## Product Code Rules

An item code uniquely identifies the purchased item.
Do NOT treat every alphanumeric string as an item code.

Do NOT extract codes that represent:
- dimensions
- specifications
- measurements
- voltages
- compatibility models
- referenced product models
- tariff / HS codes

Do NOT extract codes that:
- appear after words such as "for", "of", "compatible with", "fit", "used in", etc.
- appear only as compatibility or application information.
- appear only inside the item description without identifying the purchased item.

After identifying valid item codes:
- if only one valid item code exists:
    - toto_number = that code
    - customer_number = null

- if two valid item codes exist:
    - first valid item code = toto_number
    - second valid item code = customer_number

The customer_number may be identical to the toto_number.
Do not assume that two different product codes must exist.
Never fabricate missing product codes.

---

## Validation Rules

Before producing the final output:

- Verify that Quantity x Unit Price ≈ Extension whenever Extension is available.
- If values do not match, re-read the table and correct any OCR column shifts.
- Ensure every product code belongs to the correct purchased line item.
- Merge adjacent OCR continuation rows before returning the final JSON.
- The number of output items must equal the number of purchased line items.

A valid purchased line item MUST contain:
- exactly one toto_number
- one quantity
- one unit_price

If adjacent rows contain complementary information for the same purchased item (for example, one row contains only the product code while the next row contains only quantity and price), they MUST be merged into a single item.

Do NOT return:
- an item with a toto_number but missing quantity or unit_price;
- an item with quantity or unit_price but missing toto_number;
- multiple JSON objects representing different OCR fragments of the same purchased item.

Before returning the JSON, repeatedly merge adjacent incomplete rows until every item is complete or no further merge is possible.

---

## Output Invariants

The output is INVALID if any item satisfies any of the following:

- toto_number is null
- quantity is null
- unit_price is null

The output is INVALID if two adjacent JSON objects could be merged into a single complete purchased item.

If the output is invalid, repair it before returning the JSON.

---

## Output Schema
{
  "po_number": "",
  "po_date": "",
  "items": [
    {
      "toto_number": "",
      "customer_number": "",
      "quantity": 0,
      "unit_price": 0
    }
  ]
}
""".strip()

EXTRACTION_SCHEMA_NAME = "document_extraction"

EXTRACTION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "po_number": {"type": "string"},
        "po_date": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "toto_number": {"type": "string"},
                    "customer_number": {"type": ["string", "null"]},
                    "quantity": {"type": "number"},
                    "unit_price": {"type": "number"},
                },
                "required": [
                    "toto_number",
                    "customer_number",
                    "quantity",
                    "unit_price",
                ],
                "additionalProperties": False,
              },
          },
     },
    "required": ["po_number", "po_date", "items"],
    "additionalProperties": False,
}
