from fetchers import fetch_orders, fetch_summary, fetch_user


def run_pipeline(user_id: int) -> dict:
    user = fetch_user(user_id)
    orders = fetch_orders(user_id)
    summary = fetch_summary(user_id)
    return {"user": user, "orders": orders, "summary": summary}


def run_many(user_ids: list) -> list:
    """Run the pipeline for each user id; results are in input order."""
    return [run_pipeline(uid) for uid in user_ids]
