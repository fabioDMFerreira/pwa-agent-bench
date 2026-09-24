"""Replication: ship store log frames to a sink and track what the sink has
durably acknowledged, so a failover can replay exactly the confirmed prefix.

Offset/ack semantics (the load-bearing part):
  * Frames get a global sequence number (0, 1, 2, ...) as they are shipped.
  * `acked_seq` is the sequence number of the LAST frame the sink has
    durably stored — i.e. after shipping frame N, `acked_seq == N`.
  * A failover replays sink frames with `seq <= acked_seq`; anything newer
    than that is, by definition, not yet durable anywhere and must not be
    replayed (nor counted as lost).
"""

from .errors import ReplicationError
from .log import Frame


class Replicator:
    def __init__(self, sink):
        self.sink = sink
        self._next_seq = 0
        self.acked_seq = -1  # nothing durable yet
        self._log = None
        self.shipped = 0

    def bind_log(self, log) -> None:
        self._log = log

    def ship(self, frame: Frame) -> int:
        """Append one frame payload to the sink and advance the ack.

        Returns the sequence number assigned to the frame.
        """
        try:
            seq = self.sink.append(frame.payload)
        except Exception as exc:  # noqa: BLE001 - surface as domain error
            raise ReplicationError(f"sink write failed: {exc}") from exc
        if seq != self._next_seq:
            raise ReplicationError(
                f"sink sequence mismatch: got {seq}, expected {self._next_seq}"
            )
        self._next_seq += 1
        self.shipped += 1
        # The sink durably stored this frame, so it is the last acked one.
        self.acked_seq = seq
        return seq

    def replay_sink(self):
        """Yield (op, key, value) for every durably acked frame, in order."""
        from . import crc

        for payload in self.sink.replay(self.acked_seq):
            yield crc.decode_payload(payload)

    def stats(self) -> dict:
        return {
            "shipped": self.shipped,
            "acked_seq": self.acked_seq,
            "sink_size": len(self.sink),
            "in_flight": self.shipped - (self.acked_seq + 1),
        }