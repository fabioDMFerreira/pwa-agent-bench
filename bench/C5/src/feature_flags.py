"""Feature-flag system: store, segment rules, atomic save, and a small CLI.

Python stdlib only. See TASK.md for the full specification.
"""

import argparse
import hashlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_FLAG_FIELDS = ("name", "enabled", "rollout_percent", "allowlist", "rules")
_RULE_OPERATORS = ("in", "not_in")


def _validate_rule(rule: Any, index: int) -> None:
    if not isinstance(rule, dict):
        raise ValueError(f"rules[{index}]: rule must be a dict")
    keys = set(rule)
    if "attribute" not in keys:
        raise ValueError(f"rules[{index}]: missing 'attribute' key")
    operator_keys = keys & set(_RULE_OPERATORS)
    if len(operator_keys) != 1 or keys != {"attribute", *operator_keys}:
        raise ValueError(
            f"rules[{index}]: rule must have exactly the keys "
            f"'attribute' and one of {sorted(_RULE_OPERATORS)}"
        )
    attribute = rule["attribute"]
    if not isinstance(attribute, str) or not attribute:
        raise ValueError(f"rules[{index}]: 'attribute' must be a non-empty string")
    for operator in operator_keys:
        values = rule[operator]
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise ValueError(f"rules[{index}]: {operator!r} must be a list of strings")


@dataclass
class Flag:
    name: str
    enabled: bool = False
    rollout_percent: int = 0
    allowlist: list[str] = field(default_factory=list)
    rules: list[dict] = field(default_factory=list)

    def validate(self) -> None:
        """Raise ValueError if any field violates the data-model rules."""
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("name: must be a non-empty string")
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled: must be a bool")
        if (
            isinstance(self.rollout_percent, bool)
            or not isinstance(self.rollout_percent, int)
            or not (0 <= self.rollout_percent <= 100)
        ):
            raise ValueError("rollout_percent: must be an integer 0-100")
        if not isinstance(self.allowlist, list) or not all(
            isinstance(v, str) for v in self.allowlist
        ):
            raise ValueError("allowlist: must be a list of strings")
        if not isinstance(self.rules, list):
            raise ValueError("rules: must be a list")
        for i, rule in enumerate(self.rules):
            _validate_rule(rule, i)

    def to_dict(self) -> dict:
        """Serialize with every field written explicitly."""
        return {
            "name": self.name,
            "enabled": self.enabled,
            "rollout_percent": self.rollout_percent,
            "allowlist": list(self.allowlist),
            "rules": [dict(r) for r in self.rules],
        }


def _flag_from_dict(data: Any) -> Flag:
    if not isinstance(data, dict):
        raise ValueError("each flag entry must be a JSON object")
    unknown = set(data) - set(_FLAG_FIELDS)
    if unknown:
        raise ValueError(f"unknown keys in flag entry: {sorted(unknown)}")
    if "name" not in data:
        raise ValueError("flag entry is missing required key 'name'")
    flag = Flag(
        name=data["name"],
        enabled=data.get("enabled", False),
        rollout_percent=data.get("rollout_percent", 0),
        allowlist=data.get("allowlist", []),
        rules=data.get("rules", []),
    )
    flag.validate()
    return flag


def bucket(flag_name: str, user_id: str) -> int:
    """Deterministic 0-99 bucket; identical across processes and runs."""
    return int(hashlib.md5(f"{flag_name}:{user_id}".encode()).hexdigest()[:8], 16) % 100


class FlagStore:
    """In-memory flag store backed by a JSON file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._flags: dict[str, Flag] = {}

    # -- persistence -------------------------------------------------
    def load(self) -> None:
        """Load flags from disk. A missing file means an empty store.

        If the content is invalid, the in-memory flags are left untouched.
        """
        if not self.path.exists():
            self._flags = {}
            return
        try:
            raw = self.path.read_text()
        except OSError as exc:
            raise ValueError(f"cannot read {self.path}: {exc}") from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{self.path}: invalid JSON: {exc}") from exc
        if not isinstance(data, list):
            raise ValueError(f"{self.path}: top-level JSON must be a list")
        parsed: dict[str, Flag] = {}
        for entry in data:
            flag = _flag_from_dict(entry)
            if flag.name in parsed:
                raise ValueError(f"duplicate flag name: {flag.name!r}")
            parsed[flag.name] = flag
        self._flags = parsed

    def save(self) -> None:
        """Atomically write all flags: temp file in the same dir, then os.replace.

        Pretty-printed (2-space indent), flags sorted by name, every field
        written explicitly, trailing newline. On failure the existing file is
        left untouched, no temp file is left behind, and the error propagates
        as ValueError.
        """
        entries = sorted(
            (flag.to_dict() for flag in self._flags.values()), key=lambda d: d["name"]
        )
        content = json.dumps(entries, indent=2) + "\n"
        directory = self.path.parent
        if str(directory) in ("", "."):
            directory = Path.cwd()
        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{self.path.name}.", suffix=".tmp", dir=directory
            )
        except OSError as exc:
            raise ValueError(f"cannot write {self.path}: {exc}") from exc
        data = content.encode("utf-8")
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.close(fd)
            os.replace(tmp_name, self.path)
        except OSError as exc:
            self._cleanup(fd, tmp_name)
            raise ValueError(f"cannot write {self.path}: {exc}") from exc
        except BaseException:
            self._cleanup(fd, tmp_name)
            raise

    @staticmethod
    def _cleanup(fd: int, tmp_name: str) -> None:
        for op, arg in ((os.close, fd), (os.unlink, tmp_name)):
            try:
                op(arg)
            except OSError:
                pass

    # -- accessors ----------------------------------------------------
    def get(self, name: str) -> Flag | None:
        return self._flags.get(name)

    def names(self) -> list[str]:
        return sorted(self._flags)

    # -- mutations ------------------------------------------------------
    def upsert(self, flag: Flag) -> None:
        """Validate, then add or replace by name. Store unchanged on error."""
        flag.validate()
        self._flags[flag.name] = flag

    def remove(self, name: str) -> bool:
        return self._flags.pop(name, None) is not None

    # -- evaluation -----------------------------------------------------
    def is_enabled(self, name: str, user_id: str, attributes: dict | None = None) -> bool:
        flag = self._flags.get(name)
        if flag is None:
            return False
        if not flag.enabled:
            return False
        if user_id in flag.allowlist:
            return True
        if attributes is None:
            attributes = {}
        for rule in flag.rules:
            attribute = rule["attribute"]
            if attribute not in attributes:
                return False
            value = attributes[attribute]
            if "in" in rule:
                if value not in rule["in"]:
                    return False
            else:
                if value in rule["not_in"]:
                    return False
        return bucket(name, user_id) < flag.rollout_percent


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class _UsageError(Exception):
    pass


def _parse_attrs(pairs: list[str]) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise _UsageError(f"--attr expects KEY=VALUE, got {pair!r}")
        attributes[key] = value
    return attributes


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="feature_flags",
        description="Manage feature flags stored in a JSON file.",
    )
    parser.add_argument("--file", required=True, help="path to the flags JSON file")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list all flags")
    sub.add_parser("enable", help="set a flag's enabled=True").add_argument("name")
    sub.add_parser("disable", help="set a flag's enabled=False").add_argument("name")

    check = sub.add_parser("check", help="evaluate a flag for a user")
    check.add_argument("name", help="flag name")
    check.add_argument("user_id", help="user id")
    check.add_argument(
        "--attr",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="user attribute (repeatable)",
    )
    return parser


def main(argv: list[str]) -> int:
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code

    store = FlagStore(args.file)
    try:
        store.load()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.command == "list":
        for name in store.names():
            flag = store.get(name)
            state = "on" if flag.enabled else "off"
            print(f"{flag.name} {state} {flag.rollout_percent}%")
        return 0

    if args.command in ("enable", "disable"):
        flag = store.get(args.name)
        if flag is None:
            print(f"error: unknown flag {args.name!r}", file=sys.stderr)
            return 1
        flag.enabled = args.command == "enable"
        try:
            store.save()
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"{args.name} {'enabled' if flag.enabled else 'disabled'}")
        return 0

    if args.command == "check":
        try:
            attributes = _parse_attrs(args.attr)
        except _UsageError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print("on" if store.is_enabled(args.name, args.user_id, attributes) else "off")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
