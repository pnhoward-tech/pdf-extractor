# Bank statement bulk extractor

Point it at a folder of statement PDFs, get a validated transaction CSV and a
reconciliation report. Nothing ships unless it balances to the penny.

```bash
sudo apt-get install poppler-utils tesseract-ocr   # or: brew install poppler tesseract
python -m statements.cli extract ./inbox --ocr -o ./out
```

The profile is detected per file, so a folder can hold statements from several
banks and accounts at once.

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
python -m statements.cli extract ./inbox --ocr               # read scanned statements
python -m statements.cli extract ./inbox --include-failed    # ship CHECK rows anyway
python -m statements.cli dump statement.pdf --page 2 --ruler # derive a new profile
python -m statements.cli dump scan.pdf --ocr --ruler         # same, for a scan
python -m statements.cli profiles                            # list layouts
```

Exit codes: `0` everything reconciled, `2` at least one statement flagged,
`1` a usage or environment error.

## Profiles

| Profile | Account | Validated against |
|---|---|---|
| `hsbc-us` | HSBC Bank USA — Premier / personal checking (USD) | 2 statements, 52 transactions |
| `hsbc-uk` | HSBC UK — Premier / current account (GBP) | 1 statement, 152 transactions |
| `hsbc-uk-card` | HSBC UK — Premier credit cards (GBP) | 2 statements, 119 transactions |
| `whitaker-us` | Whitaker Bank of Kentucky — personal checking (USD), scanned | 2 statements, 3 transactions |

Every one reconciles to the penny against the totals its bank printed.

## Recognising a statement

`--profile auto` is the default. Each profile already describes what its
statements look like — the header that opens the transaction table, the labels
in the summary box, the vocabulary of type codes — so a document is scored
against those descriptions rather than against a separate signature that would
have to be kept in step with them.

```
Profile selection
  20240315_Statement.pdf:   matched hsbc-uk-card (100%: summary 100%, table 100%, codes 100%, period 100%)
  20260729_Statement_1.pdf: matched hsbc-uk (100%: summary 100%, table 100%, codes 100%, period 100%)
  DDA_20260114.pdf:         matched whitaker-us (100%: summary 100%, table 100%, codes 100%, period 100%)
```

Pass `-p <name>` to override.

## A bank you have not seen before

When nothing scores well enough, the statement is read for its own structure
instead: which column of dates opens the transaction lines, how those dates
should be read, where the amount columns sit, whether there is a code column,
and which summary-box wording the bank uses. Extraction proceeds with what that
finds.

**This gives a draft, not a finished profile.** Inference reliably gets the date
format, the amount columns and the code vocabulary; it is weaker on multi-line
transactions and unusual summary wordings. That is safe because the result goes
through the same reconciliation gate as everything else: if the inference is
wrong, the statement does not balance and its rows are held back rather than
shipped. Expect to spend a few minutes finishing the profile off.

```bash
python -m statements.cli learn new-bank.pdf
```

`learn` scores the document against existing profiles, prints what it inferred,
does a trial extraction so you can see how far it got, and emits a profile
module ready to save into `statements/profiles/` and refine.

### What inference works out, and how

* **The date format.** `03/04` is 3 April or 4 March depending on the bank, and
  guessing wrong moves a transaction by months. The choice is made on the whole
  column rather than one date: a format that parses every value wins, and where
  both do, the one whose dates run in order wins.
* **The amount columns**, by clustering the end positions of amounts across the
  table and discarding clusters too far left to be anything but description.
* **The code column**, from short tokens that recur after the date. A merchant's
  first word rarely repeats; `DD` does.
* **The summary box**, by looking for any of the wordings banks use for opening,
  closing, paid-in and paid-out beside a total.

### The layouts differ more than you'd expect

|  | HSBC US current | HSBC UK current | HSBC UK card |
|---|---|---|---|
| Type code | Description prefix (`PURCHASE ON`) | A column: `DD`, `VIS`, `CR`, `)))` … | None — a date pair opens the transaction |
| Dates | `MM/DD/YY` month-first | `DD Mon YY` day-first | Two per line: posting **and** transaction |
| Amounts | Deposits left of withdrawals | Paid-out left of paid-in | One column, `CR` suffix marks the reverse |
| Balance found by | The `$` sigil | Its column band | Not printed at all |
| Balance direction | Money in raises it | Money in raises it | Money **out** raises it — it is what you owe |

All dates are normalised to ISO `YYYY-MM-DD` on the way out, so a mixed batch
can't silently swap day and month.

### Credit cards

A card is a liability account: spending increases the balance, so the check is
`opening + out - in == closing`. Getting that backwards is a silent, plausible
wrong answer, so `balance_sign` is explicit per profile and a test asserts the
wrong convention fails.

Two card-specific traps, both caught the hard way:

* **Interest is a transaction.** The statement's Debits total includes the
  interest charged, so the `TOTAL INTEREST CHARGED` line must be picked up or
  the statement comes up short by exactly that amount.
* **Its itemised breakdown must not be.** The per-rate line above the total,
  and the estimate for next month below it, would each double-count.

## Scanned statements

Some statements arrive as images with no text layer. Without `--ocr` these are
reported as scans rather than silently yielding no transactions:

```bash
python -m statements.cli extract ./inbox --ocr
```

OCR renders each page at 300dpi and rebuilds fixed-width layout text from
tesseract's word boxes, so the column logic applies unchanged. Tokens that are
already mostly numeric get digit/letter confusions repaired (`.O0` to `.00`,
`O1/11/2024` to `01/11/2024`); words are never touched.

**What OCR can and cannot be trusted for.** The reconciliation check catches a
misread *amount*, because the statement stops balancing. It cannot catch a
digit misread as another digit in a date — a real statement here scanned
`12/14/2023` as `12/14/2025`, which is indistinguishable from correct input.
Two guards help: a statement period that runs backwards is flagged, as are
transactions dated outside their period. Beyond that, rows from a scan are
stamped `ocr` in `reconciliation_note` so they can be spot-checked.

### Writing a profile by hand

```bash
python -m statements.cli dump new-statement.pdf --page 2 --ruler
```

Copy the profile whose bank and account type is closest, then set: the header regex that opens the
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

## Several accounts at once

A batch can mix banks, currencies and account holders. Each row carries where
it came from:

| Column | |
|---|---|
| `source_account` | the channel code you pass with `--account-label`, or the account id |
| `account_id` | the bank's own identifier, masked to its last four digits |
| `owner` | whose account it is, read from the statement |
| `bank` | which institution |
| `currency` | the account's currency; `foreign_currency` and `foreign_amount` hold the original where a transaction was converted |

Cardholders are tracked within a statement, not just across files: an HSBC card
statement that covers two cards attributes each section's transactions to the
cardholder named beside that card number.

## The same transaction in two places

A card payment appears on the card statement as a purchase and on the bank
statement as the direct debit that settled it. These are found by matching
amount and currency exactly, then date proximity and merchant similarity, and
tagged in `duplicate_group` and `duplicate_of`.

**Nothing is removed.** Which copy belongs in the books is a judgement about the
accounts, not about the documents, so both rows are kept and marked. Use
`--no-dedupe` to skip the check, or `--duplicate-window` to change how many days
apart two records of one movement may be dated (default 5).

## Dates

Date fields vary more than anything else between banks, so every date is
checked against what the statement already says rather than trusted because it
parsed. Each row carries a `date_confidence`:

| Value | |
|---|---|
| `certain` | the column is corroborated by the statement period and by the order the rows are printed in |
| `day_month_unverified` | parsed, but nothing in the document rules out the other reading |
| `outside_period` | dated outside the period the statement covers |
| `order_suspect` | too many rows out of order — the day and month may be swapped |
| `missing` | no date could be read |

Roughly 40% of dates are ambiguous in isolation — any day of 12 or less — so
the reading is judged for the column as a whole. Order is judged on the posting
date where a statement prints one, since a card lists by when the bank received
a transaction rather than when it happened, and on nothing at all for
statements that group transactions under "credits" and "debits" headings rather
than by date.

## Output

`transactions.csv` carries `source_file`, `account_label`, `page_number`,
`sheet_number`, `statement_period_start`, `statement_period_end`, `txn_date`,
`type_code`, `description`, `paid_out`, `paid_in`, `amount`, `currency`,
`foreign_amount`, `foreign_currency`, `running_balance`,
`direction_confidence`, `reconciliation_note`, and `posting_date`.

Then `posting_date`, `source_account`, `account_id`, `owner`, `bank`,
`type_label`, `date_confidence`, `duplicate_group` and `duplicate_of`.

Everything after `reconciliation_note` is appended, so the agreed schema is
still the first eighteen columns in the same order — a loader reading by name,
or by position up to `reconciliation_note`, is unaffected. A test asserts this.

`posting_date` is populated only where the bank prints both dates. Card
statements do, and `txn_date` then holds the transaction date rather than the
date the bank received it.

`type_code` is always the bank's own code, verbatim; `type_label` carries what
the profile understands it to mean, alongside rather than instead of it.

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
| A statement yields nothing and warns about a text layer | It is a scan; re-run with `--ocr`. |
| Statement period runs backwards | A misread year, almost always from OCR. |
| A card statement is short by the interest amount | The `TOTAL INTEREST CHARGED` line is not being picked up. |

## Tests

```bash
pytest tests/bank
```

All fixtures are synthetic layout text shaped like the real statements —
invented merchants and amounts, no real financial data in the repository. The
parser accepts pre-extracted text, so the suite needs neither PDFs nor poppler.
