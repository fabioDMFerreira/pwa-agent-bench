# H1 Findings — `balance()` wrong when refunds exceed charges?

**Verdict:** the reported behavior is real, but the report's diagnosis is wrong
and the requested fix would break documented, tested behavior. **No code change
was made.** `balance([charge 40.00, refund 55.00]) == -15.00` is correct per
this module's spec.

## What was checked

1. **Reproduced the report exactly.**

   ```python
   balance([Txn(date(2026, 3, 2), "charge", Decimal("40.00")),
            Txn(date(2026, 3, 2), "refund", Decimal("55.00"))])
   # -> Decimal('-15.00')
   ```

   Confirmed. `daily_net` agrees: `{2026-03-02: -15.00}`.

2. **Ran the existing test suite** (`cd bench/H1 && python3 -m pytest -q`):
   11 passed before and after this investigation.

3. **Read the implementation** (`src/ledger.py`). `balance()` validates each
   transaction, filters on `as_of`, then sums `±amount` into a running total
   and quantizes to cents. There is no per-day ordering, no
   refund-before-charge application, no state that could make the order of
   postings matter.

4. **Tested the report's mechanism hypothesis directly.** Reversing the
   transaction list (refund applied before the charge) yields the same result:

   | transaction list order | `balance()` result |
   | --- | --- |
   | charge 40.00, then refund 55.00 | `-15.00` |
   | refund 55.00, then charge 40.00 | `-15.00` |

   So "the refund is being applied before the charge on the same day" is not
   what is happening — the code sums transactions, so order within a day (or
   across days) cannot affect the result. `test_order_independent` pins this
   down as intended behavior.

5. **Checked what the spec says a negative balance means** (`ledger.py`
   module docstring):

   > A **negative** balance is a *credit* in the customer's favour. It is
   > deliberately NOT clamped to zero: a refund may relate to a charge on an
   > earlier statement, or be a goodwill credit, and the credit carries
   > forward to offset future charges. Clamping would silently destroy money
   > owed to the customer. (See finance policy FIN-7: "credits are
   > liabilities, never discarded".)

   And the existing suite pins this as a requirement:
   `test_credit_carries_forward_to_later_charges` asserts
   `balance(txns, as_of=D1) == Decimal("-20.00")` and
   `balance(txns) == Decimal("-5.00")` for a goodwill refund that exceeds the
   following charge. Clamping the balance at zero would make those assertions
   fail, and TASK.md forbids modifying existing tests.

## What this means about the report

- The **observed value** (`-15.00`) is reproducible and is the correct
  computation: 40.00 charge − 55.00 refund = −15.00.
- The **diagnosis** in the report ("refund applied before the charge on the
  same day") is incorrect; there is no same-day ordering in the code and the
  result is order-independent, which I verified empirically.
- The **prescription** ("a balance can't be negative — it should be 0.00")
  contradicts the documented spec and finance policy FIN-7. C-104's refund was
  for a double-charge on their *February* statement, i.e. exactly the
  carry-forward-credit case the spec describes: C-104 is owed 15.00, which
  offsets future charges. Clamping to 0.00 would silently discard 15.00 of the
  customer's credit.

## What I changed

Nothing in `src/ledger.py`. There is no bug in the balance calculation, and
the only fix the report asks for (clamp at zero) is a spec violation, not a
bug fix — implementing it would fail `test_credit_carries_forward_to_later_charges`.

## Suggested follow-ups (out of scope for this task)

1. Discuss the `-15.00` with billing support: it is a credit in C-104's
   favour, likely intentional. If a *display* concern is the real issue, the
   fix belongs in the billing UI ("shows as 15.00 credit"), not in
   `balance()`.
2. If the business genuinely decides credits must not carry forward, that is a
   spec change: update the docstring/FIN-7 reference **and**
   `test_credit_carries_forward_to_later_charges` together — which this task
   explicitly does not allow.