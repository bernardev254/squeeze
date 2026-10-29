from __future__ import annotations

from typing import Protocol

from domain.common import TimeWindow
from domain.enums import Audience, ConsequenceType, InsightStatus, InsightType, PatternType
from domain.insights.candidate import InsightCandidate
from domain.insights.insight import (
    AudienceRepresentations,
    CommentatorRepresentation,
    FanRepresentation,
    Insight,
    OverlayRepresentation,
    StudioRepresentation,
)
from domain.match.match import MatchContext
from domain.patterns.base import Pattern


class InsightExplainer(Protocol):
    def explain(self, candidate: InsightCandidate, pattern: Pattern, context: MatchContext) -> Insight:
        ...

    def represent(self, insight: Insight, context: MatchContext) -> AudienceRepresentations:
        ...


class TemplateInsightExplainer:
    def explain(self, candidate: InsightCandidate, pattern: Pattern, context: MatchContext) -> Insight:
        team = context.home_team if pattern.team_id == context.home_team.team_id else context.away_team
        evidence_text = "; ".join(e.explanation for e in pattern.evidence[:2])
        if pattern.pattern_type == PatternType.PRESSURE_SHIFT:
            insight_type = InsightType.PRESSURE_SHIFT
            claim = f"{team.name} have significantly increased their pressure."
        elif pattern.pattern_type == PatternType.COUNTERATTACK:
            insight_type = InsightType.COUNTERATTACK
            claim = f"{team.name} created a high-value transition attack."
        elif pattern.pattern_type == PatternType.PLAYER_INFLUENCE:
            insight_type = InsightType.PLAYER
            claim = f"A {team.short_name} player is driving multiple phases."
        elif pattern.pattern_type == PatternType.HALF_SPACE_EXPLOITATION:
            insight_type = InsightType.SPATIAL
            claim = f"{team.name} are repeatedly exploiting a half-space."
        else:
            insight_type = InsightType.CONTROL
            claim = f"{team.name} pattern detected: {pattern.pattern_type.value.replace('_', ' ').title()}."
        return Insight(
            match_id=context.match_id,
            insight_type=insight_type,
            detected_at=pattern.detected_at,
            team_id=pattern.team_id,
            player_id=pattern.player_id,
            importance=pattern.significance,
            confidence=pattern.confidence,
            observation_window=TimeWindow(start=pattern.observation_window.start, end=pattern.observation_window.end),
            pattern_id=pattern.pattern_id,
            candidate_id=candidate.candidate_id,
            evidence=pattern.evidence,
            claim=claim,
            explanation=f"{claim} Evidence: {evidence_text}.",
            consequences=[c.consequence_type for c in pattern.consequences] or [ConsequenceType.TERRITORY_GAIN],
            audiences=list(Audience),
            status=InsightStatus.AVAILABLE,
        )

    def represent(self, insight: Insight, context: MatchContext) -> AudienceRepresentations:
        team = context.home_team if insight.team_id == context.home_team.team_id else context.away_team
        evidence = insight.evidence or []
        primary_metric = evidence[0].metric.replace("_", " ").title() if evidence else "Pattern"
        primary_value = str(evidence[0].value) if evidence else ""
        trigger = self._trigger_summary(evidence, team)
        pattern = self._pattern_summary(insight, team)
        why_it_matters = self._why_it_matters(insight, team)
        player_name = self._player_name(insight, context)
        match_swing = self._match_swing_summary(insight, player_name)

        return AudienceRepresentations(
            fan=FanRepresentation(
                text=f"Trigger: {trigger}. Pattern: {pattern}. {player_name} is the key driver. Why it matters: {why_it_matters}. Match swing: {match_swing}."
            ),
            commentator=CommentatorRepresentation(
                text=f"Trigger: {trigger}. Pattern: {pattern}. {player_name} is the key driver here, and the match swing is {match_swing}. Tactical effect: {why_it_matters}."
            ),
            studio=StudioRepresentation(
                headline=f"{team.name} - {insight.insight_type.value.replace('_', ' ').title()}",
                lines=[
                    f"Trigger: {trigger}",
                    f"Pattern: {pattern}",
                    f"Key driver: {player_name}",
                    f"Match swing: {match_swing}",
                    f"Why it matters: {why_it_matters}",
                    f"Confidence: {insight.confidence:.0%}",
                    f"Metric: {primary_metric} {primary_value}".strip(),
                ],
            ),
            overlay=OverlayRepresentation(
                headline=insight.insight_type.value.replace("_", " "),
                stat=f"{player_name} | {match_swing}",
            ),
        )

    @staticmethod
    def _trigger_summary(evidence: list, team: object) -> str:
        if not evidence:
            return f"{team.name} disrupted the structure in possession"
        description = evidence[0].explanation.strip()
        return description[:120].rstrip(".") if len(description) > 120 else description.rstrip(".")

    @staticmethod
    def _pattern_summary(insight: Insight, team: object) -> str:
        if insight.insight_type == InsightType.COUNTERATTACK:
            return f"{team.name} moved the ball quickly from turnover to final third with direct runners"
        if insight.insight_type == InsightType.PRESSURE_SHIFT:
            return f"{team.name} squeezed the ball-carrier and forced the next action earlier than expected"
        if insight.insight_type == InsightType.PLAYER:
            return f"A key {team.short_name} player repeatedly received and advanced the ball in the central lane"
        if insight.insight_type == InsightType.SPATIAL:
            return f"{team.name} overloaded the half-space and broke the defensive line repeatedly"
        return f"{team.name} created a structured phase that changed the rhythm of the match"

    @staticmethod
    def _why_it_matters(insight: Insight, team: object) -> str:
        if insight.consequences:
            mapped = [
                "turnover pressure",
                "final-third access",
                "box entry",
                "a shot on goal",
                "territorial gain",
                "a direct attacking threat",
            ]
            consequence_phrase = mapped[min(len(mapped) - 1, len(insight.consequences) - 1)]
            return f"it created {consequence_phrase} and forced the opponent to defend deeper"
        return f"it increased {team.name}'s control and made the next action far more dangerous"

    @staticmethod
    def _player_name(insight: Insight, context: MatchContext) -> str:
        if insight.player_id is None:
            return "the team"
        for player in context.players_on_pitch:
            if player.player_id == insight.player_id:
                return player.name
        return "the key player"

    @staticmethod
    def _match_swing_summary(insight: Insight, player_name: str) -> str:
        if insight.evidence and insight.evidence[0].metric == "phase_swing":
            value = float(insight.evidence[0].value)
            if value >= 0.4:
                return f"strong match swing in {player_name}'s favour"
            if value >= 0.25:
                return f"measurable match swing in {player_name}'s favour"
            return f"modest match swing in {player_name}'s favour"
        return f"the phase shifted in {player_name}'s favour"
