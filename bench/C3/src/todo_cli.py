import argparse
import json
import sys
from pathlib import Path

STATE_FILE = Path("state.json")


def load_state():
    if not STATE_FILE.exists():
        return []
    return json.loads(STATE_FILE.read_text())


def save_state(items):
    STATE_FILE.write_text(json.dumps(items, indent=2))


def cmd_add(args):
    items = load_state()
    items.append({"text": args.text, "done": False})
    save_state(items)
    print(f"added: {args.text}")


def cmd_list(args):
    items = load_state()
    if not items:
        print("(no todos)")
        return
    for i, item in enumerate(items, start=1):
        mark = "x" if item["done"] else " "
        print(f"{i}. [{mark}] {item['text']}")


def cmd_done(args):
    items = load_state()
    try:
        index = int(args.index)
    except (TypeError, ValueError):
        print(f"todo: invalid index: {args.index!r} (expected an integer)", file=sys.stderr)
        sys.exit(1)
    if not 1 <= index <= len(items):
        print(f"todo: index out of range: {index}", file=sys.stderr)
        sys.exit(1)
    items[index - 1]["done"] = True
    save_state(items)
    print(f"done: {items[index - 1]['text']}")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="todo")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add")
    p_add.add_argument("text")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list")
    p_list.set_defaults(func=cmd_list)

    p_done = sub.add_parser("done")
    p_done.add_argument("index")
    p_done.set_defaults(func=cmd_done)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
