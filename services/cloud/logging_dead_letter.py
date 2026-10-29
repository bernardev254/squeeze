from __future__ import annotations

import logging
from services.cloud.dead_letter import DeadLetterRecord, DeadLetterSink

logger = logging.getLogger(__name__)


class LoggingDeadLetterSink(DeadLetterSink):
    """Simple dead-letter sink that logs records for local testing."""

    def record(self, record: DeadLetterRecord) -> None:
        logger.warning("dead_letter_recorded", extra={"event_id": str(record.event_id), "match_id": str(record.match_id), "reason": record.failure_reason})
