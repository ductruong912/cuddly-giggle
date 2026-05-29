from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

import httpx

from app.domain.schemas import PageParseResult


class QwenVerifier:
    """
    Optional verifier for low-confidence pages using an OpenAI-compatible endpoint.
    Expected response schema:
    {
      "corrections": [
        {"block_id": "blk_xxx", "content": "corrected text", "confidence": 0.91}
      ]
    }
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float = 60.0,
        chat_path: str = "/v1/chat/completions",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.chat_path = chat_path

    def verify_page(self, input_path: str, page: PageParseResult) -> dict[str, Any] | None:
        if not self.base_url:
            return None

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a strict OCR verifier. Return JSON only: "
                        '{"corrections":[{"block_id":"...", "content":"...", "confidence":0.0}]}. '
                        "Only return corrections you are highly confident about."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self._build_page_prompt(page)},
                        {"type": "image_url", "image_url": {"url": self._to_file_url(input_path)}},
                    ],
                },
            ],
            "temperature": 0.0,
        }

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(f"{self.base_url}{self.chat_path}", headers=headers, json=payload)
                response.raise_for_status()
            data = response.json()
        except Exception:
            return None

        try:
            content = data["choices"][0]["message"]["content"]
        except Exception:
            return None

        # Some providers wrap JSON in markdown fences.
        content = self._strip_code_fence(str(content))

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        return parsed

    @staticmethod
    def _strip_code_fence(content: str) -> str:
        # Remove only a leading ```/```lang fence and a trailing ``` fence. The old
        # strip("`") + replace("json", "", 1) deleted backticks and the first "json"
        # substring anywhere in the body, corrupting content that contained them.
        content = content.strip()
        content = re.sub(r"^```[a-zA-Z0-9]*\n?", "", content)
        content = re.sub(r"\n?```$", "", content)
        return content.strip()

    def _build_page_prompt(self, page: PageParseResult) -> str:
        lines = []
        lines.append(f"Page index: {page.page_index}")
        lines.append("Current OCR blocks:")
        for block in page.blocks:
            lines.append(f"- {block.block_id} ({block.type}, conf={block.confidence:.2f}): {block.content}")
        return "\n".join(lines)

    @staticmethod
    def _to_file_url(input_path: str) -> str:
        # OpenAI-compatible servers vary; file:// works in some self-hosted stacks.
        return Path(input_path).resolve().as_uri()
