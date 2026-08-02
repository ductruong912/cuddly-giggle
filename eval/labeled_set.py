"""The labeled set: ground truth for each document the harness scores against.

A case is either a *document* case, which runs the real pipeline against a file
on disk, or a *replay* case, which feeds recorded model answers straight into the
validation loop. Replay cases exist so the harness can measure the self-healing
retry loop without an OCR engine, an API key, or a document corpus.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
from typing import Any

# pyrefly: ignore [missing-import]
from pydantic import ValidationError

from core.domain.purchase_order import PurchaseOrder


logger = logging.getLogger(__name__)

MANIFEST_SUFFIX = "*.json"


class LabeledSetError(Exception):
    """The labeled set is missing, unreadable, or contains a malformed case."""


@dataclass(frozen=True)
class EvalCase:
    """One ground-truth record, and the input that should reproduce it."""

    case_id: str
    expected: dict[str, Any]
    description: str = ""
    document: Path | None = None
    attempts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_replay(self) -> bool:
        """True when the case replays recorded answers instead of reading a file."""
        return self.document is None


class LabeledSet:
    """Load and sanity-check every ground-truth manifest under a directory."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def load(self) -> list[EvalCase]:
        """Read every manifest in the directory and return the cases in file order.

        Raises:
            LabeledSetError: the directory is missing, a manifest is not valid
                JSON, or a case is malformed or has a duplicate id.
        """
        if not self.root.is_dir():
            raise LabeledSetError(f"labeled set directory does not exist: {self.root}")

        manifests = sorted(self.root.glob(MANIFEST_SUFFIX))
        if not manifests:
            raise LabeledSetError(f"no *.json manifests found in {self.root}")

        cases: list[EvalCase] = []
        seen: set[str] = set()
        for manifest in manifests:
            for raw_case in self._read_manifest(manifest):
                case = self._build_case(raw_case, manifest)
                if case.case_id in seen:
                    raise LabeledSetError(
                        f"duplicate case_id {case.case_id!r} in {manifest.name}"
                    )
                seen.add(case.case_id)
                cases.append(case)

        logger.info("loaded %s case(s) from %s manifest(s)", len(cases), len(manifests))
        return cases

    @staticmethod
    def _read_manifest(manifest: Path) -> list[dict[str, Any]]:
        try:
            with manifest.open(encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            logger.exception("could not read labeled-set manifest %s", manifest)
            raise LabeledSetError(f"{manifest.name} is not readable JSON: {exc}") from exc

        cases = payload.get("cases") if isinstance(payload, dict) else None
        if not isinstance(cases, list):
            raise LabeledSetError(f"{manifest.name} must be an object with a 'cases' list")
        return cases

    def _build_case(self, raw_case: dict[str, Any], manifest: Path) -> EvalCase:
        if not isinstance(raw_case, dict):
            raise LabeledSetError(f"{manifest.name} contains a case that is not an object")

        case_id = str(raw_case.get("case_id", "")).strip()
        if not case_id:
            raise LabeledSetError(f"{manifest.name} contains a case with no case_id")

        expected = raw_case.get("expected")
        if not isinstance(expected, dict):
            raise LabeledSetError(f"case {case_id!r} has no 'expected' record")
        self._warn_if_ground_truth_is_invalid(case_id, expected)

        document = raw_case.get("document")
        attempts = raw_case.get("attempts")
        if document and attempts:
            raise LabeledSetError(
                f"case {case_id!r} sets both 'document' and 'attempts'; it must set exactly one"
            )
        if not document and not attempts:
            raise LabeledSetError(
                f"case {case_id!r} sets neither 'document' nor 'attempts'"
            )
        if attempts is not None and not isinstance(attempts, list):
            raise LabeledSetError(f"case {case_id!r} has a non-list 'attempts'")

        return EvalCase(
            case_id=case_id,
            expected=expected,
            description=str(raw_case.get("description", "")),
            # Document paths are written relative to the manifest that names them,
            # so a labeled set stays portable when the repo moves.
            document=(manifest.parent / str(document)).resolve() if document else None,
            attempts=list(attempts or []),
        )

    @staticmethod
    def _warn_if_ground_truth_is_invalid(case_id: str, expected: dict[str, Any]) -> None:
        """Flag ground truth the pipeline could never score as valid.

        A real document may genuinely state a line total that does not reconcile.
        That is worth knowing about — it caps the achievable validity rate — but
        it is not a reason to refuse to score the case.
        """
        try:
            PurchaseOrder.model_validate(expected)
        except ValidationError as exc:
            logger.warning(
                "ground truth for case %s does not satisfy PurchaseOrder (%s); "
                "this case can never be scored valid",
                case_id,
                "; ".join(str(detail.get("msg", "")) for detail in exc.errors()[:2]),
            )
