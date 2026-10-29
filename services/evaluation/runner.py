from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import yaml
from pydantic import Field

from domain.common import DomainModel
from domain.enums import PatternType
from services.agents.gateway import AgentGateway
from services.agents.orchestrator import AgentOrchestrator
from services.match_engine.processor import MatchProcessor
from services.settings import Settings
from simulator.scenarios import EXPECTATIONS, generate_scenario


class EvaluationCase(DomainModel):
    case_id: str
    scenario: str
    seed: int = 42
    expected_patterns: list[PatternType] = Field(default_factory=list)
    expected_consequences: list[str] = Field(default_factory=list)


class PatternScore(DomainModel):
    pattern_type: PatternType
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0


class EvaluationReport(DomainModel):
    cases: int
    scores: list[PatternScore]
    overall_f1: float
    structural_passes: int
    structural_failures: int
    agent_schema_checks: int = 0
    grounding_checks: int = 0
    hallucination_checks: int = 0
    mutation_checks: int = 0
    fallback_checks: int = 0


def default_cases() -> list[EvaluationCase]:
    return [
        EvaluationCase(
            case_id=f"{scenario}_001",
            scenario=scenario,
            seed=42,
            expected_patterns=expectation.expected_patterns,
            expected_consequences=expectation.expected_consequences,
        )
        for scenario, expectation in EXPECTATIONS.items()
        if expectation.expected_patterns
    ]


def load_cases(path: str | Path = "evals/datasets/phase2_cases.yaml") -> list[EvaluationCase]:
    dataset = Path(path)
    if not dataset.exists():
        return default_cases()
    raw = yaml.safe_load(dataset.read_text()) or []
    return [EvaluationCase.model_validate(item) for item in raw]


def run_evaluation(
    cases: list[EvaluationCase] | None = None,
    agent_gateway: AgentGateway | None = None,
    settings: Settings | None = None,
) -> EvaluationReport:
    cases = cases or load_cases()
    expected_by_pattern: dict[PatternType, int] = defaultdict(int)
    detected_by_pattern: dict[PatternType, int] = defaultdict(int)
    true_by_pattern: dict[PatternType, int] = defaultdict(int)
    structural_passes = 0
    structural_failures = 0
    agent_schema_checks = 0
    grounding_checks = 0
    hallucination_checks = 0
    mutation_checks = 0
    fallback_checks = 0
    for case in cases:
        bundle = generate_scenario(case.scenario, case.seed)
        processor = MatchProcessor(context=bundle.context)
        for event in bundle.events:
            processor.process_event(event)
        detected = {pattern.pattern_type for pattern in processor.patterns}
        expected = set(case.expected_patterns)
        for pattern_type in expected:
            expected_by_pattern[pattern_type] += 1
            if pattern_type in detected:
                true_by_pattern[pattern_type] += 1
        for pattern_type in detected:
            detected_by_pattern[pattern_type] += 1
        for pattern in processor.patterns:
            if pattern.evidence and any(
                chain.pattern_id == pattern.pattern_id for chain in processor.causal_chains
            ):
                structural_passes += 1
            else:
                structural_failures += 1
        for validation in processor.validations:
            structural_passes += int(validation.valid)
            structural_failures += int(not validation.valid)
        if processor.insights and agent_gateway is not None:
            orchestrator = AgentOrchestrator(processor, settings or Settings(), gateway=agent_gateway)
            result = orchestrator.invoke_for_insight(processor.insights[-1].insight_id)
            structural_passes += int(bool(result.narratives))
            agent_schema_checks += sum(response.status.value == "SUCCEEDED" for response in result.responses)
            grounding_checks += sum(
                bool(claim.evidence_ids or claim.event_refs or claim.metric_refs)
                for claim in result.trace.claims
            )
            hallucination_checks += sum(
                not claim.text.lower().count("xg") for claim in result.trace.claims
            )
            mutation_checks += sum(validation.valid for validation in processor.validations)
            fallback_checks += int(not result.fallback_used)
    scores: list[PatternScore] = []
    all_patterns = set(expected_by_pattern) | set(detected_by_pattern)
    for pattern_type in sorted(all_patterns, key=lambda item: item.value):
        tp = true_by_pattern[pattern_type]
        fp = max(0, detected_by_pattern[pattern_type] - tp)
        fn = max(0, expected_by_pattern[pattern_type] - tp)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
        scores.append(
            PatternScore(
                pattern_type=pattern_type,
                true_positives=tp,
                false_positives=fp,
                false_negatives=fn,
                precision=round(precision, 3),
                recall=round(recall, 3),
                f1=round(f1, 3),
            )
        )
    overall = round(sum(score.f1 for score in scores) / len(scores), 3) if scores else 0.0
    return EvaluationReport(
        cases=len(cases),
        scores=scores,
        overall_f1=overall,
        structural_passes=structural_passes,
        structural_failures=structural_failures,
        agent_schema_checks=agent_schema_checks,
        grounding_checks=grounding_checks,
        hallucination_checks=hallucination_checks,
        mutation_checks=mutation_checks,
        fallback_checks=fallback_checks,
    )
