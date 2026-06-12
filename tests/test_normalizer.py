from __future__ import annotations

from app.services.engines.paddle.normalizer import normalize_engine_output


class DummyResult:
    def __init__(self, json_payload: dict, markdown_payload: dict) -> None:
        self.json = json_payload
        self.markdown = markdown_payload


def test_normalizer_parsing_res_list_and_table_html() -> None:
    raw = {
        "pages": [
            {
                "parsing_res_list": [
                    {
                        "block_label": "text",
                        "block_content": "Xin chao",
                        "block_bbox": [0, 0, 100, 20],
                        "block_id": "b1",
                        "block_order": 0,
                    },
                    {
                        "block_label": "table",
                        "block_content": "<table><tr><td>A</td><td>B</td></tr></table>",
                        "block_bbox": [0, 30, 100, 80],
                        "block_id": "t1",
                        "block_order": 1,
                    },
                ]
            }
        ],
        "markdown": {"markdown_texts": "Xin chao\n\n<table><tr><td>A</td><td>B</td></tr></table>"},
    }

    pages, markdown, _ = normalize_engine_output(raw, source_engine="unit")
    assert len(pages) == 1
    assert markdown is not None and "Xin chao" in markdown
    assert len(pages[0].blocks) == 2
    assert any(block.content == "Xin chao" for block in pages[0].blocks)
    assert len(pages[0].tables) == 1
    assert len(pages[0].tables[0].cells) == 2


def test_normalizer_accepts_result_object_style_payload() -> None:
    json_payload = {
        "res": {
            "parsing_res_list": [
                {
                    "block_label": "text",
                    "block_content": "Hello markdown",
                    "block_bbox": [0, 0, 20, 20],
                    "block_id": "b1",
                }
            ]
        }
    }
    markdown_payload = {"markdown_texts": "Hello markdown"}
    raw = [DummyResult(json_payload=json_payload, markdown_payload=markdown_payload)]

    pages, markdown, _ = normalize_engine_output(raw, source_engine="unit")
    assert len(pages) == 1
    assert pages[0].blocks[0].content == "Hello markdown"
    assert markdown == "Hello markdown"

