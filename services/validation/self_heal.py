"""Re-ask the model with the exact validation errors, rather than re-rolling.

A blind retry is a coin flip. Feeding back the specific field and the specific
arithmetic that failed ("quantity 4 x unit_price 125000 = 500000, but the stated
extension is 50000") turns the retry into a targeted correction.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any, Protocol

# pyrefly: ignore [missing-import]
from pydantic import ValidationError

from config.config import Settings, settings
from config.pipeline_logging import pipeline_message
from core.domain.purchase_order import PurchaseOrder
from core.domain.schemas import ParseResponse
from services.validation.business_rules import BusinessRuleChecker, RuleViolation, Severity


logger = logging.getLogger(__name__)


class StructuredExtractor(Protocol):
    """The extraction call this loop drives."""

    def extract(
        self,
        parse_response: ParseResponse,
        *,
        correction: str | None = None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ExtractionOutcome:
    """What the loop produced, and whether it can be trusted."""

    data: dict[str, Any]
    record: PurchaseOrder | None
    violations: list[RuleViolation] = field(default_factory=list)
    attempts: int = 1

    @property
    def is_valid(self) -> bool:
        """True when nothing blocking remains; warnings do not make it invalid."""
        return self.record is not None and not self.blocking_violations

    @property
    def blocking_violations(self) -> list[RuleViolation]:
        return [v for v in self.violations if v.severity is Severity.error]

    @property
    def healed(self) -> bool:
        """True when the first attempt failed but a later one succeeded."""
        return self.attempts > 1 and self.is_valid


class SelfHealingExtractor:
    """Extract, validate, and re-ask with the failures until valid or out of tries."""

    def __init__(
        self,
        extractor: StructuredExtractor,
        checker: BusinessRuleChecker | None = None,
        app_settings: Settings = settings,
    ) -> None:
        self.extractor = extractor
        self.checker = checker or BusinessRuleChecker()
        self.settings = app_settings

    def extract(self, parse_response: ParseResponse) -> ExtractionOutcome:
        """Run the extract/validate/correct loop and report the final outcome."""
        correction: str | None = None
        data: dict[str, Any] = {}
        violations: list[RuleViolation] = []
        max_attempts = 1 + max(0, self.settings.llm_self_heal_max_retries)

        for attempt in range(1, max_attempts + 1):
            data = self.extractor.extract(parse_response, correction=correction)
            record, violations = self._validate(data)

            blocking = [v for v in violations if v.severity is Severity.error]
            if record is not None and not blocking:
                if attempt > 1:
                    logger.info(
                        pipeline_message("PHASE 3", "validation recovered on attempt %s/%s"),
                        attempt,
                        max_attempts,
                    )
                return ExtractionOutcome(data=data, record=record, violations=violations, attempts=attempt)

            if attempt == max_attempts:
                break

            logger.warning(
                pipeline_message("PHASE 3", "validation failed on attempt %s/%s: %s; re-asking"),
                attempt,
                max_attempts,
                "; ".join(v.message for v in blocking[:3]),
            )
            correction = build_correction_prompt(data, blocking)

        logger.warning(
            pipeline_message("PHASE 3", "validation still failing after %s attempt(s); needs review"),
            max_attempts,
        )
        return ExtractionOutcome(data=data, record=None, violations=violations, attempts=max_attempts)

    def _validate(self, data: dict[str, Any]) -> tuple[PurchaseOrder | None, list[RuleViolation]]:
        try:
            record = PurchaseOrder.model_validate(data)
        except ValidationError as exc:
            return None, _violations_from_pydantic(exc)
        return record, self.checker.check(record)


def _violations_from_pydantic(error: ValidationError) -> list[RuleViolation]:
    """Turn Pydantic's error list into violations that name the failing field."""
    violations: list[RuleViolation] = []
    for detail in error.errors():
        location = ".".join(str(part) for part in detail.get("loc", ())) or "(root)"
        message = str(detail.get("msg", "")).removeprefix("Value error, ")
        violations.append(RuleViolation(field=location, message=message, severity=Severity.error))
    return violations


def build_correction_prompt(data: dict[str, Any], violations: list[RuleViolation]) -> str:
    """Compose a correction that names each failing field and what was wrong.

    The previous answer is quoted back so the model corrects it rather than
    starting over and reproducing the same misreading.
    """
    numbered = "\n".join(
        f"{index}. field `{violation.field}`: {violation.message}"
        for index, violation in enumerate(violations, start=1)
    )
    return (
        "Your previous answer failed validation. Re-read the document and correct "
        "it.\n\n"
        f"Previous answer:\n{data}\n\n"
        f"Problems found:\n{numbered}\n\n"
        "Fix only what is wrong. Re-read the affected rows in the document rather "
        "than adjusting numbers to make the arithmetic work: a mismatch usually "
        "means a column was read from the wrong position, not that a value needs "
        "rounding. Return the corrected JSON in the same schema."
    )
