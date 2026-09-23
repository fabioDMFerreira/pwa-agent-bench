"""Error hierarchy for kve."""


class KveError(Exception):
    """Base class for all kve errors."""


class CorruptionError(KveError):
    """A stored frame failed its checksum or could not be parsed."""


class NotFoundError(KveError):
    """Raised by explicit lookup helpers when a key is absent."""


class ReplicationError(KveError):
    """Replication channel failure (sink write, bad ack, ...)."""


class StoreClosedError(KveError):
    """Operation attempted on a closed store."""