"""Edit this module to adapt LLM extraction to a document domain."""
from __future__ import annotations

EXTRACTION_INSTRUCTIONS = """
Bạn là hệ thống trích xuất dữ liệu Purchase Order từ OCR hoặc HTML.

Chỉ lấy dữ liệu xuất hiện rõ ràng trong tài liệu. Không suy đoán hoặc tự tạo dữ
liệu. Trường không tìm thấy hoặc không chắc chắn phải trả về chuỗi rỗng "".

Trích xuất:

* so_po: số PO, không lấy Reference hoặc mã khác. Khi header có dạng
  `Order No. - <số PO> <mã loại đơn/hậu tố>`, chỉ lấy số PO; không lấy mã loại
  đơn/hậu tố, tên chi nhánh, hoặc nhãn cột khác đứng sau số PO.
* ngay_po: ngày PO, không lấy Delivery Date, Requested Date hoặc Revise Date.
* danh_sach_hang: mỗi dòng hàng hợp lệ là một phần tử riêng, không gộp các dòng
  trùng mã.

Với mỗi item:

* ma_hang_khach_hang: chỉ điền khi xác định rõ là mã hàng khách hàng; nếu không
  thì "".
* ma_hang_toto: mã hàng TOTO, không lấy mô tả sản phẩm.
* so_luong: số lượng trong cột Quantity hoặc Ordered.
* don_gia: đơn giá trong cột Unit Price hoặc Unit Cost, không lấy Amount hoặc
  Total.

OCR có thể tách một dòng hàng thành nhiều dòng văn bản. Hãy ghép các phần liên
tiếp khi chúng rõ ràng thuộc cùng một dòng hàng. Đặc biệt, một dòng tiếp nối
chỉ chứa các mã hàng phải được ghép vào dòng hàng ngay trước đó có mô tả,
so_luong hoặc don_gia, không được bỏ qua hay tạo item mới.

Khi một item có hai mã hàng liên tiếp, mã đứng trước thường là
ma_hang_khach_hang và mã đứng sau là ma_hang_toto. Không gán mã đầu tiên làm
ma_hang_toto rồi bỏ mã thứ hai. Chỉ dùng quy tắc này khi cả hai mã rõ ràng
thuộc cùng một dòng hàng/ngữ cảnh hàng.

Trong bảng OCR bị lệch cột, xác định so_luong từ cột Ordered/Quantity và
don_gia từ Unit Cost/Unit Price theo header/ngữ cảnh, không dựa đơn thuần vào
vị trí cột. Mã HS/thuế, Extension, Amount và Total không phải don_gia; nếu
trong cùng ô có mã HS/thuế và một giá trị đơn giá riêng, chỉ lấy giá trị đơn giá
đó làm don_gia.

Không tạo item từ dòng chỉ chứa mô tả, số lượng, đơn giá hoặc số rời rạc. Nếu
không xác định được mã hàng TOTO thì không tạo item đó.

so_luong và don_gia phải là một giá trị số duy nhất. Nếu OCR ghép nhiều số
vào cùng một giá trị và không thể xác định chắc chắn, trả về "".

Giữ nguyên định dạng ngày, số lượng và đơn giá sau khi làm sạch khoảng trắng thừa.

Trả về đúng JSON Schema, không trả về giải thích hoặc Markdown.
""".strip()

EXTRACTION_SCHEMA_NAME = "document_extraction"

EXTRACTION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "so_po": {"type": "string"},
        "ngay_po": {"type": "string"},
        "danh_sach_hang": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ma_hang_khach_hang": {"type": "string"},
                    "ma_hang_toto": {"type": "string"},
                    "so_luong": {"type": "string"},
                    "don_gia": {"type": "string"},
                },
                "required": [
                    "ma_hang_khach_hang",
                    "ma_hang_toto",
                    "so_luong",
                    "don_gia",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["so_po", "ngay_po", "danh_sach_hang"],
    "additionalProperties": False,
}
