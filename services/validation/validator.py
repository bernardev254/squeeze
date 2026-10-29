from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import Field

from domain.common import DomainModel, utc_now
from domain.enums import ValidationCheckType, ValidationStatus
from domain.insights.claim import InsightClaim
from domain.insights.evidence import EvidenceRef
from domain.patterns.base import Pattern


class ValidationCheck(DomainModel):
    check_type: ValidationCheckType
    status: ValidationStatus
    detail: str


class ValidationResult(DomainModel):
    validation_id: UUID = Field(default_factory=uuid4)
    valid: bool
    claim_id: UUID
    checks: list[ValidationCheck]
    failed_checks: list[ValidationCheck]
    evidence: list[EvidenceRef]
    validated_at: datetime = Field(default_factory=utc_now)
    validator_version: str = "deterministic.validator.v2"
    validation_confidence: float = Field(ge=0.0, le=1.0)


class InsightValidator:
    def validate(self, claim: InsightClaim, pattern: Pattern) -> ValidationResult:
        checks = [
            self._check(
                ValidationCheckType.TEAM_MATCH,
                claim.subject_team_id == pattern.team_id,
                "claim team matches pattern team",
            ),
            self._check(
                ValidationCheckType.PATTERN,
                claim.pattern_id == pattern.pattern_id and claim.pattern_type == pattern.pattern_type,
                "claim pattern matches detected pattern",
            ),
            self._check(
                ValidationCheckType.EVIDENCE_LINK,
                self._evidence_is_supported(claim, pattern),
                "claim evidence is linked to detected pattern evidence",
            ),
            self._check(
                ValidationCheckType.TIME_WINDOW,
                claim.observation_window.duration_seconds >= 0,
                "claim window is valid",
            ),
            self._metric_value_check(claim, pattern),
            self._baseline_check(claim),
            self._check(
                ValidationCheckType.CAUSAL_SUPPORT,
                bool(pattern.causes) or bool(pattern.consequences),
                "pattern carries causal or consequence support",
            ),
            self._check(
                ValidationCheckType.CONSEQUENCE,
                bool(pattern.consequences),
                "pattern has deterministic consequences",
            ),
        ]
        failed = [check for check in checks if check.status == ValidationStatus.FAIL]
        confidence = round(sum(check.status == ValidationStatus.PASS for check in checks) / len(checks), 3)
        return ValidationResult(
            valid=not failed,
            claim_id=claim.claim_id,
            checks=checks,
            failed_checks=failed,
            evidence=claim.evidence,
            validation_confidence=confidence,
        )

    def _check(self, check_type: ValidationCheckType, passed: bool, detail: str) -> ValidationCheck:
        return ValidationCheck(
            check_type=check_type,
            status=ValidationStatus.PASS if passed else ValidationStatus.FAIL,
            detail=detail,
        )

    def _metric_value_check(self, claim: InsightClaim, pattern: Pattern) -> ValidationCheck:
        metric = str(claim.object.get("metric", ""))
        current = claim.object.get("current")
        supported = current is not None and any(
            e.metric == metric and self._same_value(e.value, current) for e in pattern.evidence
        )
        return self._check(
            ValidationCheckType.METRIC_VALUE,
            bool(metric) and current is not None and supported,
            f"{metric} current value is supported by pattern evidence",
        )

    def _same_value(
        self,
        left: float | str | int,
        right: float | str | int | None,
    ) -> bool:
        if right is None:
            return False
        try:
            return float(left) == float(right)
        except (TypeError, ValueError):
            return str(left) == str(right)

    def _evidence_is_supported(self, claim: InsightClaim, pattern: Pattern) -> bool:
        if not claim.evidence:
            return False
        pattern_evidence_ids = {evidence.evidence_id for evidence in pattern.evidence}
        pattern_event_ids = {event_id for evidence in pattern.evidence for event_id in evidence.event_ids}
        pattern_impact_ids = {impact_id for evidence in pattern.evidence for impact_id in evidence.impact_ids}
        pattern_metrics = {evidence.metric for evidence in pattern.evidence}
        for evidence in claim.evidence:
            if evidence.evidence_id not in pattern_evidence_ids:
                return False
            if evidence.metric not in pattern_metrics:
                return False
            if evidence.event_ids and not set(evidence.event_ids).issubset(pattern_event_ids):
                return False
            if evidence.impact_ids and not set(evidence.impact_ids).issubset(pattern_impact_ids):
                return False
        return True

    def _baseline_check(self, claim: InsightClaim) -> ValidationCheck:
        baseline = claim.object.get("previous", claim.object.get("baseline"))
        return self._check(
            ValidationCheckType.BASELINE,
            baseline is not None,
            "claim contains a comparison baseline",
        )
