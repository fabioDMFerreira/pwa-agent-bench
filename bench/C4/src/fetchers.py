"""Fake data fetchers — imagine these are network calls."""

import asyncio

# Simulated per-call network latency in seconds (tests may change it).
LATENCY = 0.05


class UserNotFound(Exception):
    """Raised when a user id does not exist (ids must be >= 1)."""


async def fetch_user(user_id: int) -> dict:
    await asyncio.sleep(LATENCY)
    if user_id < 1:
        raise UserNotFound(user_id)
    return {"id": user_id, "name": f"user{user_id}"}


async def fetch_orders(user_id: int) -> list:
    await asyncio.sleep(LATENCY)
    return [
        {"order_id": 100 + user_id, "amount": 10.0},
        {"order_id": 200 + user_id, "amount": 20.0},
    ]


async def fetch_summary(user_id: int) -> dict:
    await asyncio.sleep(LATENCY)
    return {"user_id": user_id, "lifetime_value": 500.0}
