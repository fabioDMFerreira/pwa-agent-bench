from dataclasses import dataclass, field


@dataclass(frozen=True)
class Event:
    """One recorded event.

    position     global, 1-based, gap-free order across all streams
    stream       stream name, e.g. "order-42"
    version      1-based position within its stream
    type         event type, e.g. "OrderPlaced"
    data         JSON-serialisable payload
    id           unique event id (hex string)
    recorded_at  unix timestamp (float seconds) when appended
    """

    position: int
    stream: str
    version: int
    type: str
    data: dict = field(default_factory=dict)
    id: str = ""
    recorded_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "position": self.position,
            "stream": self.stream,
            "version": self.version,
            "type": self.type,
            "data": self.data,
            "id": self.id,
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        return cls(**d)
