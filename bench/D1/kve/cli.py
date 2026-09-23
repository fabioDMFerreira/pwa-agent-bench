"""Command-line interface: `python -m kve.cli <command> <store-dir> ...`

Commands:
  put <key> <value>   write one key
  get <key>           print the value (or "nil")
  scan [start] [end]  inclusive range dump
  stats               store health summary
  dump                dump table segments (capped)
"""

import sys

from .client import Client
from .stats import compact_advice, store_health_summary
from .utils import chunked, human_bytes


def _open(directory):
    return Client(directory)


def cmd_put(args):
    directory, key, value = args[0], args[1], args[2]
    with _open(directory) as kv:
        kv.put(key, value)
    print(f"put {key} = {value}")


def cmd_get(args):
    directory, key = args[0], args[1]
    with _open(directory) as kv:
        value = kv.get(key)
    print("nil" if value is None else value)


def cmd_scan(args):
    directory = args[0]
    start = args[1] if len(args) > 1 else None
    end = args[2] if len(args) > 2 else None
    with _open(directory) as kv:
        for k, v in chunked(list(kv.scan(start, end)), 50):
            for kk, vv in k:
                print(f"{kk}={vv}")


def cmd_stats(args):
    directory = args[0]
    summary = store_health_summary(directory)
    for key, value in sorted(summary.items()):
        if key == "total_table_bytes":
            print(f"{key}={human_bytes(value)}")
        else:
            print(f"{key}={value}")
    print(f"advice={compact_advice(summary)}")


def cmd_dump(args):
    directory = args[0]
    from . import log

    for seg in log.Log(directory / "wal").segments():
        print(f"-- {seg.name} --")
        from . import segment as _segment

        print(_segment.dump_segment(seg))


COMMANDS = {
    "put": cmd_put,
    "get": cmd_get,
    "scan": cmd_scan,
    "stats": cmd_stats,
    "dump": cmd_dump,
}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] not in COMMANDS:
        print("usage: python -m kve.cli <put|get|scan|stats|dump> <dir> [args...]", file=sys.stderr)
        return 2
    try:
        COMMANDS[argv[0]](argv[1:])
    except Exception as exc:  # noqa: BLE001 - CLI reports, doesn't crash
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())