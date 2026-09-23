"""User directory. Backed by a dict here; in production each lookup is a DB
round-trip, so `queries` counts round-trips and callers should prefer the
batch `get_many` over repeated `get` calls."""

from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    id: int
    name: str
    webhook_url: str | None
    locale: str = "en"
    active: bool = True


class UserDirectory:
    def __init__(self, users):
        self._users = {u.id: u for u in users}
        self.queries = 0

    def get(self, user_id: int) -> User | None:
        """One round-trip. Returns None for unknown ids."""
        self.queries += 1
        return self._users.get(user_id)

    def get_many(self, user_ids) -> dict[int, User]:
        """One round-trip for the whole batch. Unknown ids are omitted."""
        self.queries += 1
        return {uid: self._users[uid] for uid in user_ids if uid in self._users}
