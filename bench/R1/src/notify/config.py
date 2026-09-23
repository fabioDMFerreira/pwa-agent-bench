"""Service settings, read from a mapping of environment variables."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    api_token: str
    max_attempts: int = 3
    base_delay: float = 0.5  # seconds
    max_delay: float = 8.0  # seconds
    timeout: float = 5.0  # seconds, per HTTP request

    @classmethod
    def from_env(cls, env: dict) -> "Settings":
        """Build settings from env vars.

        NOTIFY_API_TOKEN      required
        NOTIFY_MAX_ATTEMPTS   int, default 3
        NOTIFY_BASE_DELAY     float seconds, default 0.5
        NOTIFY_MAX_DELAY      float seconds, default 8
        NOTIFY_TIMEOUT_MS     int milliseconds, default 5000
        """
        token = env.get("NOTIFY_API_TOKEN")
        if not token:
            raise ValueError("NOTIFY_API_TOKEN is required")
        return cls(
            api_token=token,
            max_attempts=int(env.get("NOTIFY_MAX_ATTEMPTS", 3)),
            base_delay=float(env.get("NOTIFY_BASE_DELAY", 0.5)),
            max_delay=float(env.get("NOTIFY_MAX_DELAY", 8.0)),
            timeout=float(env.get("NOTIFY_TIMEOUT_MS", 5000)) / 100,
        )
