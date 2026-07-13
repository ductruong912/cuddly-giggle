"""Edit this module to adapt LLM extraction to a document domain."""
from __future__ import annotations

EXTRACTION_INSTRUCTIONS = """
Bạn là hệ thống trích xuất dữ liệu Purchase Order từ OCR hoặc HTML.

Chỉ lấy dữ liệu xuất hiện rõ ràng trong tài liệu. Không suy đoán hoặc tự tạo dữ
liệu. Trường không tìm thấy hoặc không chắc chắn phải trả về chuỗi rỗng "".

Trích xuất:

* po_number: số PO, không lấy Reference hoặc mã khác.
* po_date: ngày PO, không lấy Delivery Date, Requested Date hoặc Revise Date.
* items: mỗi dòng hàng hợp lệ là một phần tử riêng, không gộp các dòng trùng mã.

Với mỗi item:

* customer_item_code: chỉ điền khi xác định rõ là mã hàng khách hàng; nếu không
  thì "".
* toto_item_code: mã hàng TOTO, không lấy mô tả sản phẩm.
* quantity: số lượng trong cột Quantity hoặc Ordered.
* unit_price: đơn giá trong cột Unit Price hoặc Unit Cost, không lấy Amount hoặc
  Total.

OCR có thể tách một dòng hàng thành nhiều dòng văn bản. Hãy ghép các phần liên
tiếp khi chúng rõ ràng thuộc cùng một dòng hàng.

Không tạo item từ dòng chỉ chứa mô tả, số lượng, đơn giá hoặc số rời rạc. Nếu
không xác định được mã hàng TOTO thì không tạo item đó.

quantity và unit_price phải là một giá trị số duy nhất. Nếu OCR ghép nhiều số
vào cùng một giá trị và không thể xác định chắc chắn, trả về "".

Giữ nguyên định dạng ngày, số lượng và đơn giá sau khi làm sạch khoảng trắng thừa.

Trả về đúng JSON Schema, không trả về giải thích hoặc Markdown.
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
                    "customer_item_code": {"type": "string"},
                    "toto_item_code": {"type": "string"},
                    "quantity": {"type": "string"},
                    "unit_price": {"type": "string"},
                },
                "required": [
                    "customer_item_code",
                    "toto_item_code",
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
