from __future__ import annotations

from pathlib import Path

from domain.agents.gateway import PromptVersion
from domain.enums import AgentRole


class PromptRegistry:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path("prompts")

    def list_prompts(self) -> list[PromptVersion]:
        prompts: list[PromptVersion] = []
        for role in AgentRole:
            prompt = self.get(role, "v1")
            if prompt:
                prompts.append(prompt)
        return prompts

    def get(self, role: AgentRole, version: str = "v1") -> PromptVersion | None:
        path = self.root / role.value.lower() / f"{version}.md"
        if not path.exists():
            return None
        text = path.read_text()
        return PromptVersion(
            name=f"{role.value.lower()}-{version}",
            version=version,
            purpose=_extract_field(text, "purpose") or f"{role.value} agent prompt",
            input_schema=_extract_field(text, "input_schema") or "structured context",
            output_schema=_extract_field(text, "output_schema") or "structured output",
            safety_rules=[
                "Supplied SQUEEZE context is authoritative.",
                "Do not invent events, statistics, players, or match state.",
                "Do not calculate or revise deterministic metrics, action impact, score, possession, or time windows.",
                "Every factual claim must reference supplied evidence.",
                "Distinguish observed facts from interpretation.",
            ],
        )


def _extract_field(text: str, field: str) -> str | None:
    prefix = f"{field}:"
    for line in text.splitlines():
        if line.lower().startswith(prefix):
            return line.split(":", 1)[1].strip()
    return None
