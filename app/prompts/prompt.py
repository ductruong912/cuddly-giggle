"""Edit this module to adapt LLM extraction to a document domain."""
from __future__ import annotations

EXTRACTION_INSTRUCTIONS = """
Bạn là hệ thống trích xuất dữ liệu Purchase Order từ OCR hoặc HTML.

Chỉ lấy dữ liệu xuất hiện rõ ràng trong tài liệu. Không suy đoán hoặc tự tạo dữ
liệu. Trường không tìm thấy hoặc không chắc chắn phải trả về chuỗi rỗng "".

Trích xuất:

* po_number: số PO, không lấy Reference hoặc mã khác. Khi header có dạng
  `Order No. - <số PO> <mã loại đơn/hậu tố>`, chỉ lấy số PO; không lấy mã loại
  đơn/hậu tố, tên chi nhánh, hoặc nhãn cột khác đứng sau số PO.
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
tiếp khi chúng rõ ràng thuộc cùng một dòng hàng. Đặc biệt, một dòng tiếp nối
chỉ chứa các mã hàng phải được ghép vào dòng hàng ngay trước đó có mô tả,
quantity hoặc unit_price, không được bỏ qua hay tạo item mới.

Khi một item có hai mã hàng liên tiếp, mã đứng trước thường là
customer_item_code và mã đứng sau là toto_item_code. Không gán mã đầu tiên làm
toto_item_code rồi bỏ mã thứ hai. Chỉ dùng quy tắc này khi cả hai mã rõ ràng
thuộc cùng một dòng hàng/ngữ cảnh hàng.

Trong bảng OCR bị lệch cột, xác định quantity từ cột Ordered/Quantity và
unit_price từ Unit Cost/Unit Price theo header/ngữ cảnh, không dựa đơn thuần vào
vị trí cột. Mã HS/thuế, Extension, Amount và Total không phải unit_price; nếu
trong cùng ô có mã HS/thuế và một giá trị đơn giá riêng, chỉ lấy giá trị đơn giá
đó làm unit_price.

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
