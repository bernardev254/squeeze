class MatchEngineError(Exception):
    """Base error for deterministic match processing failures."""


class InvalidSequence(MatchEngineError):
    pass


class DuplicateEvent(MatchEngineError):
    pass


class OutOfOrderEvent(MatchEngineError):
    pass


