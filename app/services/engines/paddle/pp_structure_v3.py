from __future__ import annotations

from app.services.engines.paddle.base import PaddlePipelineEngine


class PPStructureV3Engine(PaddlePipelineEngine):
    name = "pp_structure_v3"
    cli_subcommand = "pp_structurev3"

    def _load_pipeline_cls(self) -> type:
        from paddleocr import PPStructureV3  # type: ignore

        return PPStructureV3

    def _unavailable_message(self, py_error: str, cli_error: str) -> str:
        return (
            "PP-StructureV3 is unavailable. Install paddleocr and paddlepaddle-gpu, "
            "or ensure `paddleocr` CLI exists in PATH. "
            f"python_api_error={py_error or 'n/a'}; cli_error={cli_error or 'n/a'}"
        )
