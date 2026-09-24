import asyncio

from fetchers import fetch_orders, fetch_summary, fetch_user


async def run_pipeline(user_id: int) -> dict:
    user = await fetch_user(user_id)
    orders, summary = await asyncio.gather(fetch_orders(user_id), fetch_summary(user_id))
    return {"user": user, "orders": orders, "summary": summary}


async def run_many(user_ids: list) -> list:
    """Run the pipeline for each user id; results are in input order."""
    return await asyncio.gather(*(run_pipeline(uid) for uid in user_ids))
