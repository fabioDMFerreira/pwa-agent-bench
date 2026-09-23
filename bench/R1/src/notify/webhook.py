"""Webhook delivery with retry and exponential backoff.

Retry policy (documented contract):
  * A delivery is attempted at most `max_attempts` times in total.
  * Retryable outcomes: transport errors (OSError / TimeoutError), any 5xx
    status, and 429. Every other status (2xx success, other 4xx) is final.
  * Before retry n (n = 1, 2, ...) the sender sleeps
    min(max_delay, base_delay * 2 ** (n - 1)) seconds: base, 2*base, 4*base...
  * Every request carries `Authorization: Bearer <api_token>` and an
    `X-Signature` HMAC-SHA256 of the exact body bytes sent.
"""

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger("notify.webhook")


@dataclass
class DeliveryResult:
    ok: bool
    attempts: int
    status: int | None
    error: str | None = None


class WebhookSender:
    def __init__(self, transport, settings, sleep=time.sleep):
        """`transport(url, body: bytes, headers: dict, timeout: float) -> int`
        returns the HTTP status or raises OSError/TimeoutError."""
        self.transport = transport
        self.settings = settings
        self.sleep = sleep

    def _headers(self, body: bytes) -> dict:
        sig = hmac.new(self.settings.api_token.encode(), body, hashlib.sha256).hexdigest()
        return {
            "Authorization": f"Bearer {self.settings.api_token}",
            "Content-Type": "application/json",
            "X-Signature": f"sha256={sig}",
        }

    @staticmethod
    def _should_retry(status: int) -> bool:
        return status == 429 or status > 500

    def send(self, url: str, payload: dict) -> DeliveryResult:
        body = json.dumps(payload).encode()
        headers = self._headers(body)
        status = None
        error = None
        logger.info("POST %s headers=%s", url, headers)
        for attempt in range(self.settings.max_attempts):
            if attempt:
                delay = self.settings.base_delay * 2 ** (attempt - 1)
                self.sleep(min(self.settings.max_delay, delay))
            try:
                status = self.transport(url, body, headers, self.settings.timeout)
                error = None
            except (OSError, TimeoutError) as exc:
                status, error = None, str(exc)
                logger.warning("delivery to %s failed: %s", url, exc)
                continue
            if 200 <= status < 300:
                return DeliveryResult(True, attempt + 1, status)
            if not self._should_retry(status):
                return DeliveryResult(False, attempt + 1, status)
        return DeliveryResult(False, self.settings.max_attempts, status, error)
