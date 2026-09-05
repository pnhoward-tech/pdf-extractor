# Bank statement bulk extractor

Point it at a folder of statement PDFs, get a validated transaction CSV and a
reconciliation report. Nothing ships unless it balances to the penny.

```bash
sudo apt-get install poppler-utils          # or: brew install poppler
python -m statements.cli extract ./inbox --account-label CUR1 -o ./out
```

Read `out/reconciliation.csv` first. Any statement marked `CHECK` needs
investigating before its rows are trusted — and by default its rows are not in
`out/transactions.csv` at all.

## Why the reconciliation gate matters

A statement prints its own answer: opening balance, total in, total out,
closing balance. The parser computes those independently from the transaction
lines, and the two must agree exactly. That is the difference between a number
you can load into a budget and a number that merely looks plausible.

The check runs at two levels:

* **Per segment.** Between each pair of printed balances, money in minus money
  out must equal the change in balance.
* **Per statement.** `opening + total_in - total_out == closing`, exactly.

Where a segment doesn't balance and the culprits are transactions whose type
code can't settle direction on its own, the tool tries flipping one, then all
of them together (a whole page read one column across), then a bounded subset
search. If nothing resolves it, the stretch is flagged `UNRESOLVED - manual
review` rather than guessed at.

## Commands

```bash
python -m statements.cli extract ./inbox -a CUR1 -o ./out   # the main job
python -m statements.cli extract ./inbox --profile hsbc-uk  # pick a bank layout
python -m statements.cli extract ./inbox --include-failed    # ship CHECK rows anyway
python -m statements.cli dump statement.pdf --page 2 --ruler # derive a new profile
python -m statements.cli profiles                            # list layouts
```

Exit codes: `0` everything reconciled, `2` at least one statement flagged,
`1` a usage or environment error.

## Profiles

| Profile | Bank | Status |
|---|---|---|
| `hsbc-us` | HSBC Bank USA, N.A. — Premier / personal checking (USD) | Validated against real statements |
| `hsbc-uk` | HSBC UK — Premier / current account (GBP) | Written from spec, **not yet validated against real statements** |

`hsbc-us` is the default. Run a couple of UK statements through `hsbc-uk` and
read the reconciliation report before trusting a UK batch — that report is what
would catch a wrong column number in an unvalidated profile.

### The two layouts differ more than you'd expect

|  | HSBC US | HSBC UK |
|---|---|---|
| Type code | None — classified on the description prefix (`PURCHASE ON`, `INTEREST PAID`) | A real column: `DD`, `SO`, `VIS`, `CR`, `BP`, `OBP`, `ATM`, `DR`, `)))` |
| Dates | `MM/DD/YY`, month-first | `DD Mon YY`, day-first |
| Column order | Deposits left of withdrawals | Paid-out left of paid-in |
| Balance identified by | The `$` sigil — only the balance carries one | Its column band |
| Running balance | Printed on every transaction | At checkpoints |

Both are normalised to ISO `YYYY-MM-DD` on the way out, so a mixed batch can't
silently swap day and month.

### Adding a profile

```bash
python -m statements.cli dump new-statement.pdf --page 2 --ruler
```

Copy `statements/profiles/hsbc_us.py`, then set: the header regex that opens the
transaction table (match loosely — spacing shifts between pages), the stop
marker where boilerplate begins, the summary-box patterns, the code vocabulary
with each code's direction, and the column geometry. Register it in
`statements/profiles/__init__.py`.

Mark a code `Direction.AMBIGUOUS` whenever it can post either way — a card
refund reuses the purchase code. Ambiguous codes get a provisional direction
from column position, which balance validation then confirms or flips. Codes
marked `OUT` or `IN` are never flipped, so a wrong one there becomes an
unresolvable flag rather than a silent correction.

## How column positions are handled

Column positions shift between a statement's first page (which carries the
summary box), its middle pages and its last page. Nothing is hardcoded: each
page is measured from its own content. The balance column anchors the
measurement, the amount band is taken relative to it, and lines whose type code
already settles their direction calibrate the in/out split.

This is why numbers inside a description — a foreign-currency amount, an
exchange rate, a long reference number — are not mistaken for the transaction
amount: they sit left of the calibrated amount band.

## Output

`transactions.csv` carries `source_file`, `account_label`, `page_number`,
`sheet_number`, `statement_period_start`, `statement_period_end`, `txn_date`,
`type_code`, `description`, `paid_out`, `paid_in`, `amount`, `currency`,
`foreign_amount`, `foreign_currency`, `running_balance`,
`direction_confidence`, `reconciliation_note`.

`amount` is signed positive for money out, matching the target workbook.
`direction_confidence` is `certain` when the type code settled it, or
`resolved_by_balance` when it was ambiguous and the balance check decided.

`reconciliation.csv` has one row per PDF with computed and printed totals side
by side, and `check` = `OK` or `CHECK`.

### A known quirk of HSBC US descriptions

HSBC's own PDFs pad merchant names into fixed-width chunks, so descriptions
arrive as `MARK S&SPENCER`, `TESC O STORES`, `SUMMERT OWN`. The spaces are in
the source file with the same letter spacing as real word breaks, so no
extraction method can tell them apart. Descriptions are kept verbatim for audit
fidelity; categorisation downstream reads them without trouble.

## Troubleshooting

| Symptom | Cause |
|---|---|
| A page returns zero transactions | The table-start regex missed that page's header. Run `dump --page N --ruler` and look at the actual text. |
| Total off by a large amount | A multi-line transaction parsed short — its amount is several lines below its description. |
| Total off by a small amount | One transaction on the wrong side. Flipping one moves the total by twice its amount, so look for one worth exactly half the gap; the report says this explicitly. |
| A whole page's ambiguous codes are wrong the same way | Page-wide column shift; the reconciler labels this `flipped: page-wide column recalibration`. |
| `pdftotext not found` | Install poppler-utils. |

## Tests

```bash
pytest tests/bank
```

All fixtures are synthetic layout text shaped like the real statements —
invented merchants and amounts, no real financial data in the repository. The
parser accepts pre-extracted text, so the suite needs neither PDFs nor poppler.
