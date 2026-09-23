class EventStoreError(Exception):
    """Base class for event store errors."""


class ConcurrencyError(EventStoreError):
    """Raised when `expected_version` does not match the stream's version."""
