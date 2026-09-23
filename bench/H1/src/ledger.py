"""Customer ledger balances.

A transaction is a ``Txn(day, kind, amount)``:

- ``day``    -- ``datetime.date`` the transaction was posted.
- ``kind``   -- ``"charge"`` (customer owes us more) or ``"refund"`` (we owe
  the customer / reduce what they owe).
- ``amount`` -- strictly positive ``Decimal``.

Balance semantics
-----------------
``balance(txns, as_of=None)`` is the sum of all charges minus the sum of all
refunds posted on or before ``as_of`` (every transaction when ``as_of`` is
``None``). The result is a ``Decimal`` rounded to cents (ROUND_HALF_UP).

- A **positive** balance is what the customer owes.
- A **negative** balance is a *credit* in the customer's favour. It is
  deliberately NOT clamped to zero: a refund may relate to a charge on an
  earlier statement, or be a goodwill credit, and the credit carries forward
  to offset future charges. Clamping would silently destroy money owed to the
  customer. (See finance policy FIN-7: "credits are liabilities, never
  discarded".)
- Transactions are summed, so their order -- including order within the same
  day -- does not affect the result.

Invalid input (unknown ``kind``, non-positive or non-Decimal ``amount``)
raises ``ValueError``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Optional

CENT = Decimal("0.01")
_SIGN = {"charge": Decimal(1), "refund": Decimal(-1)}


@dataclass(frozen=True)
class Txn:
    day: date
    kind: str
    amount: Decimal


def _validate(txn: Txn) -> None:
    if txn.kind not in _SIGN:
        raise ValueError(f"unknown transaction kind: {txn.kind!r}")
    if not isinstance(txn.amount, Decimal) or txn.amount <= 0:
        raise ValueError(f"amount must be a positive Decimal, got {txn.amount!r}")


def balance(txns: Iterable[Txn], as_of: Optional[date] = None) -> Decimal:
    """Return the customer's balance; negative means credit (see module docstring)."""
    total = Decimal(0)
    for txn in txns:
        _validate(txn)
        if as_of is not None and txn.day > as_of:
            continue
        total += _SIGN[txn.kind] * txn.amount
    return total.quantize(CENT, rounding=ROUND_HALF_UP)


def daily_net(txns: Iterable[Txn]) -> dict:
    """Net change per day (charges minus refunds), keyed by date, sorted."""
    out: dict = {}
    for txn in txns:
        _validate(txn)
        out[txn.day] = out.get(txn.day, Decimal(0)) + _SIGN[txn.kind] * txn.amount
    return {d: v.quantize(CENT, rounding=ROUND_HALF_UP) for d, v in sorted(out.items())}
