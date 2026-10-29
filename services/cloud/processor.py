from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from domain.common import MatchClock, Scoreline
from domain.enums import GameState, Period
from domain.events.envelope import EventEnvelope, validate_envelope_schema
from domain.events.factory import parse_event
from domain.match.match import MatchContext, Team
from services.cloud.dead_letter import DeadLetterRecord, DeadLetterSink
from services.match_engine.errors import DuplicateEvent, InvalidSequence, OutOfOrderEvent
from services.match_engine.processor import MatchProcessor, ProcessingResult
from services.repositories.match_state import (
    MatchStateRecord,
    MatchStateRepository,
)
from services.settings import Settings, load_settings

logger = logging.getLogger(__name__)


@dataclass
class Checkpoint:
    match_id: str
    sequence: int
    checkpointed: bool = False


class CloudEventProcessor:
    def __init__(
        self,
            repository: MatchStateRepository,
            dead_letters: DeadLetterSink,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        if repository is None:
            raise RuntimeError(
                "CloudEventProcessor requires a cloud-backed MatchStateRepository; do not use in-memory repositories."
            )
        if dead_letters is None:
            raise RuntimeError(
                "CloudEventProcessor requires a dead-letter sink implementation; configure a cloud-backed sink."
            )
        self.repository = repository
        self.dead_letters = dead_letters
        self.checkpoints: list[Checkpoint] = []
        self.events_received_total = 0
        self.events_processed_total = 0
        self.events_failed_total = 0
        self.events_duplicate_total = 0
        self.events_out_of_order_total = 0

    def process_envelope(self, envelope: EventEnvelope) -> ProcessingResult | None:
        self.events_received_total += 1
        try:
            validate_envelope_schema(envelope)
            event = parse_event(envelope.payload)
            record = self.repository.get(event.match_id)
            if record is None:
                record = MatchStateRecord(
                    match_id=event.match_id,
                    processor=MatchProcessor(context=_context_from_first_event(event.match_id, event.team_id)),
                )
            record = self._ensure_event_team(record, event.team_id)
            result = record.processor.process_event(event)
            snapshot_interval = self.settings.cloud_state.snapshot_interval_events
            latest_snapshot = (
                record.processor.snapshots[-1]
                if record.processor.snapshots and event.sequence % snapshot_interval == 0
                else record.latest_snapshot
            )
            saved = self.repository.save(
                record.model_copy(update={"latest_snapshot": latest_snapshot}),
                expected_version=record.version,
            )
            self.events_processed_total += 1
            self.checkpoints.append(
                Checkpoint(match_id=str(saved.match_id), sequence=event.sequence, checkpointed=True)
            )
            logger.info(
                "event_processed",
                extra={
                    "event_id": str(envelope.event_id),
                    "match_id": str(envelope.match_id),
                    "sequence": envelope.sequence,
                    "event_type": envelope.event_type,
                    "scenario": envelope.scenario,
                    "source": envelope.source,
                },
            )
            return result
        except ValueError as exc:
            self.events_failed_total += 1
            self._dead_letter(envelope, exc, "invalid envelope")
        except DuplicateEvent as exc:
            self.events_duplicate_total += 1
            if self.settings.app.app_env in {"development", "local", "test"}:
                logger.info(
                    "duplicate_event_ignored_in_dev",
                    extra={
                        "event_id": str(envelope.event_id),
                        "match_id": str(envelope.match_id),
                        "sequence": envelope.sequence,
                        "event_type": envelope.event_type,
                    },
                )
                return None
            self._dead_letter(envelope, exc, "duplicate event")
        except (InvalidSequence, OutOfOrderEvent) as exc:
            self.events_out_of_order_total += 1
            self._dead_letter(envelope, exc, "ordering violation")
        except Exception as exc:
            self.events_failed_total += 1
            self._dead_letter(envelope, exc, "processing failure")
        return None

    def _ensure_event_team(self, record: MatchStateRecord, team_id: UUID) -> MatchStateRecord:
        context = record.processor.context
        if team_id in {context.home_team.team_id, context.away_team.team_id}:
            return record
        away_team = context.away_team.model_copy(update={"team_id": team_id})
        players = [
            player.model_copy(update={"team_id": team_id})
            if player.team_id == context.away_team.team_id
            else player
            for player in context.players_on_pitch
        ]
        record.processor.context = context.model_copy(
            update={"away_team": away_team, "players_on_pitch": players}
        )
        return record

    def status(self) -> dict[str, int]:
        return {
            "events_received_total": self.events_received_total,
            "events_processed_total": self.events_processed_total,
            "events_failed_total": self.events_failed_total,
            "events_duplicate_total": self.events_duplicate_total,
            "events_out_of_order_total": self.events_out_of_order_total,
            "checkpoints": len(self.checkpoints),
        }

    def _dead_letter(self, envelope: EventEnvelope, exc: Exception, reason: str) -> None:
        logger.warning(
            "event_dead_lettered",
            extra={
                "event_id": str(envelope.event_id),
                "match_id": str(envelope.match_id),
                "sequence": envelope.sequence,
                "event_type": envelope.event_type,
                "reason": reason,
                "error_type": type(exc).__name__,
            },
        )
        self.dead_letters.record(
            DeadLetterRecord(
                event_id=envelope.event_id,
                match_id=envelope.match_id,
                failure_reason=reason,
                error_type=type(exc).__name__,
                original_payload_reference=envelope.model_dump_json(),
            )
        )


def _context_from_first_event(match_id: UUID, team_id: UUID) -> MatchContext:
    away_team_id = UUID("00000000-0000-0000-0000-000000000002")
    if away_team_id == team_id:
        away_team_id = UUID("00000000-0000-0000-0000-000000000003")
    score = Scoreline(home=0, away=0)
    return MatchContext(
        match_id=match_id,
        home_team=Team(team_id=team_id, name="Home Team", short_name="HOME"),
        away_team=Team(team_id=away_team_id, name="Away Team", short_name="AWAY"),
        current_score=score,
        period=Period.FIRST_HALF,
        current_clock=MatchClock(period=Period.FIRST_HALF, minute=0, second=0),
        players_on_pitch=[],
        game_state=GameState.DRAW,
    )
