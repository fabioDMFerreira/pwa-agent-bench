from datetime import date
from decimal import Decimal as D

import pytest

from ledger import Txn, balance, daily_net

D1, D2, D3 = date(2026, 3, 1), date(2026, 3, 2), date(2026, 3, 3)


def test_empty_is_zero():
    assert balance([]) == D("0.00")


def test_charges_minus_refunds():
    txns = [Txn(D1, "charge", D("100.00")), Txn(D2, "refund", D("30.00"))]
    assert balance(txns) == D("70.00")


def test_as_of_excludes_later_days():
    txns = [Txn(D1, "charge", D("10")), Txn(D3, "charge", D("5"))]
    assert balance(txns, as_of=D2) == D("10.00")


def test_credit_carries_forward_to_later_charges():
    txns = [
        Txn(D1, "refund", D("20.00")),  # goodwill credit
        Txn(D3, "charge", D("15.00")),
    ]
    assert balance(txns, as_of=D1) == D("-20.00")
    assert balance(txns) == D("-5.00")


def test_order_independent():
    txns = [Txn(D2, "refund", D("5")), Txn(D2, "charge", D("8")), Txn(D1, "charge", D("1"))]
    assert balance(txns) == balance(list(reversed(txns))) == D("4.00")


def test_rounds_to_cents_half_up():
    assert balance([Txn(D1, "charge", D("0.005"))]) == D("0.01")


def test_daily_net():
    txns = [Txn(D2, "charge", D("3")), Txn(D1, "charge", D("2")), Txn(D2, "refund", D("1"))]
    assert daily_net(txns) == {D1: D("2.00"), D2: D("2.00")}


@pytest.mark.parametrize("txn", [
    Txn(D1, "fee", D("1")),
    Txn(D1, "charge", D("0")),
    Txn(D1, "charge", D("-1")),
    Txn(D1, "charge", 1.5),
])
def test_invalid_rejected(txn):
    with pytest.raises(ValueError):
        balance([txn])
