from uuid import uuid4

from domain.common import MatchClock, Scoreline, TimeWindow
from domain.enums import Audience, ConsequenceType, GameState, InsightStatus, InsightType, Period
from domain.insights.evidence import EvidenceRef
from domain.insights.insight import Insight
from domain.match.match import MatchContext, Player, Team
from services.insight_engine.explainer import TemplateInsightExplainer


def _context() -> MatchContext:
    return MatchContext(
        match_id=uuid4(),
        home_team=Team(team_id=uuid4(), name="Manchester City", short_name="MCI"),
        away_team=Team(team_id=uuid4(), name="Arsenal", short_name="ARS"),
        current_score=Scoreline(home=1, away=0),
        period=Period.FIRST_HALF,
        current_clock=MatchClock(period=Period.FIRST_HALF, minute=23, second=14),
        players_on_pitch=[],
        game_state=GameState.HOME_LEADING,
    )


def test_template_explainer_delivers_elite_structure_for_fans_and_commentators() -> None:
    context = _context()
    insight = Insight(
        match_id=context.match_id,
        insight_type=InsightType.COUNTERATTACK,
        detected_at=context.current_clock,
        team_id=context.home_team.team_id,
        player_id=None,
        importance=0.82,
        confidence=0.88,
        observation_window=TimeWindow(
            start=MatchClock(period=Period.FIRST_HALF, minute=22, second=50),
            end=MatchClock(period=Period.FIRST_HALF, minute=23, second=30),
        ),
        pattern_id=uuid4(),
        evidence=[
            EvidenceRef(
                source_type="pattern",
                metric="entries_into_final_third",
                value=3.0,
                time_window="00:00-00:10",
                explanation="The attack arrived in the final third within five seconds.",
            ),
            EvidenceRef(
                source_type="event",
                metric="progressive_passes",
                value=2,
                time_window="00:00-00:10",
                explanation="The press won the ball and the second phase moved through the half-space.",
            ),
        ],
        claim="Manchester City turned an aggressive press into a rapid transition.",
        explanation="The team advanced quickly after the turnover.",
        consequences=[ConsequenceType.BOX_ENTRY, ConsequenceType.SHOT],
        audiences=list(Audience),
        status=InsightStatus.AVAILABLE,
    )

    representation = TemplateInsightExplainer().represent(insight, context)

    fan_text = representation.fan.text.lower()
    commentator_text = representation.commentator.text.lower()
    studio_lines = " ".join(representation.studio.lines).lower()

    assert "trigger" in fan_text
    assert "why it matters" in fan_text
    assert "pattern" in commentator_text
    assert "trigger" in commentator_text
    assert "why it matters" in studio_lines


def test_template_explainer_names_player_and_match_swing() -> None:
    player_id = uuid4()
    context = _context()
    context.players_on_pitch = [
        Player(player_id=player_id, team_id=context.home_team.team_id, name="Kevin De Bruyne", shirt_number=17, position="AM")
    ]
    insight = Insight(
        match_id=context.match_id,
        insight_type=InsightType.COUNTERATTACK,
        detected_at=context.current_clock,
        team_id=context.home_team.team_id,
        player_id=player_id,
        importance=0.9,
        confidence=0.9,
        observation_window=TimeWindow(
            start=MatchClock(period=Period.FIRST_HALF, minute=23, second=0),
            end=MatchClock(period=Period.FIRST_HALF, minute=23, second=20),
        ),
        pattern_id=uuid4(),
        evidence=[
            EvidenceRef(
                source_type="event",
                metric="phase_swing",
                value=0.42,
                time_window="00:20",
                explanation="The move created a rapid box entry and a direct threat.",
            )
        ],
        claim="Kevin De Bruyne accelerated the transition.",
        explanation="He drove the ball through the half-space and found the runner.",
        consequences=[ConsequenceType.BOX_ENTRY, ConsequenceType.SHOT],
        audiences=list(Audience),
        status=InsightStatus.AVAILABLE,
    )

    representation = TemplateInsightExplainer().represent(insight, context)
    text = " ".join(representation.studio.lines).lower()

    assert "kevin de bruyne" in text.lower()
    assert "match swing" in text.lower() or "shift" in text.lower()
