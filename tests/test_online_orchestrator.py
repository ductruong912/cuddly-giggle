from __future__ import annotations

import pytest

from config.config import Settings
from services.online_orchestrator import OnlineParseOrchestrator


class FailingDataLabEngine:
    def parse(self, input_path: str, lang_hint: str = "auto") -> object:
        del input_path, lang_hint
        raise RuntimeError("DataLab unavailable")


def test_online_parse_propagates_datalab_failure_without_local_fallback() -> None:
    parser = OnlineParseOrchestrator(Settings(), engine=FailingDataLabEngine())

    with pytest.raises(RuntimeError, match="DataLab unavailable"):
        parser.parse("invoice.pdf")
