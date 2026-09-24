import asyncio
import json
import sys

from fetchers import UserNotFound
from pipeline import run_many, run_pipeline


def main(argv=None) -> int:
    """Usage: cli.py [USER_ID ...]

    One id (default 1) prints that user's pipeline result as JSON; several ids
    print a JSON list in the same order. An unknown user prints
    `error: user not found: <id>` to stderr and returns 1.
    """
    argv = sys.argv[1:] if argv is None else argv
    user_ids = [int(a) for a in argv] or [1]
    try:
        if len(user_ids) == 1:
            result = asyncio.run(run_pipeline(user_ids[0]))
        else:
            result = asyncio.run(run_many(user_ids))
    except UserNotFound as exc:
        print(f"error: user not found: {exc.args[0]}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
