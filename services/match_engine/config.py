from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from domain.common import DomainModel


class IntelligenceConfig(DomainModel):
    progressive_pass_distance: float = 0.12
    pressure_threshold: float = 0.55
    high_pressure_threshold: float = 0.72
    transition_time_threshold: int = 12
    state_change_threshold: float = 0.15
    pattern_significance_threshold: float = 0.55
    candidate_priority_threshold: float = 0.35
    deduplication_window: int = 300
    insight_ttl_seconds: int = 300
    final_third_x: float = 0.67
    box_x: float = 0.84


def load_config(path: str | Path = "config/intelligence.yaml") -> IntelligenceConfig:
    config_path = Path(path)
    if not config_path.exists():
        return IntelligenceConfig()
    data: dict[str, Any] = yaml.safe_load(config_path.read_text()) or {}
    return IntelligenceConfig.model_validate(data)
