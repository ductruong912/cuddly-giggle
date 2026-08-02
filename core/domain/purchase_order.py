"""The Purchase Order record, and the invariants a valid one must satisfy.

This model does double duty: it constrains what the extraction model may emit
(via its JSON Schema) and it checks, deterministically, whether what came back
actually reconciles. The prompt asks the model to verify its own arithmetic;
that is not verification, so the arithmetic is enforced here instead.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from config.config import settings


# A line total may legitimately drift from quantity x unit_price when the
# document rounds a unit price for display. A relative tolerance absorbs that
# while still catching the real failure mode: an OCR column shift, which is
# wrong by orders of magnitude rather than by a rounding step.
LINE_TOTAL_ABSOLUTE_FLOOR = 0.01


class PurchaseOrderItem(BaseModel):
    """One purchased line item."""

    model_config = ConfigDict(extra="forbid")

    toto_number: str = Field(description="Item code identifying the purchased item.")
    customer_number: str | None = Field(
        description="Second item code when the document carries one, otherwise null."
    )
    quantity: float = Field(description="Quantity ordered.")
    unit_price: float = Field(description="Price per unit.")
    extension: float | None = Field(
        description="Line total as stated on the document, or null when not stated."
    )

    @model_validator(mode="after")
    def check_line_reconciles(self) -> PurchaseOrderItem:
        """Reject a line whose stated total cannot be reproduced from its parts."""
        if not self.toto_number.strip():
            raise ValueError("toto_number is empty")
        if self.quantity <= 0:
            raise ValueError(f"quantity must be greater than zero, got {self.quantity}")
        if self.unit_price < 0:
            raise ValueError(f"unit_price cannot be negative, got {self.unit_price}")

        if self.extension is None:
            return self

        computed = self.quantity * self.unit_price
        tolerance = max(
            LINE_TOTAL_ABSOLUTE_FLOOR,
            abs(self.extension) * settings.po_line_total_tolerance_ratio,
        )
        if abs(computed - self.extension) > tolerance:
            raise ValueError(
                f"line total mismatch: quantity {self.quantity} x unit_price "
                f"{self.unit_price} = {computed:.2f}, but the stated extension is "
                f"{self.extension:.2f}. Re-read this row; the columns may be shifted."
            )
        return self


class PurchaseOrder(BaseModel):
    """A purchase order and its line items."""

    model_config = ConfigDict(extra="forbid")

    po_number: str = Field(description="Purchase order number, digits only.")
    po_date: str = Field(description="Purchase order date in DD-MM-YYYY format.")
    items: list[PurchaseOrderItem] = Field(description="One entry per purchased line item.")

    @model_validator(mode="after")
    def check_header(self) -> PurchaseOrder:
        """Reject an order with no identifier or no line items."""
        if not self.po_number.strip():
            raise ValueError("po_number is empty")
        if not self.po_date.strip():
            raise ValueError("po_date is empty")
        if not self.items:
            raise ValueError("no line items were extracted")
        return self
