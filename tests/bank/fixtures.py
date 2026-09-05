"""Synthetic layout text shaped like the real statements.

Every merchant and amount here is invented. The parser accepts pre-extracted
layout text, so these tests need neither PDFs nor poppler installed.
"""

from __future__ import annotations

FF = "\x0c"


def place(*pieces: tuple[int, str]) -> str:
    """Build a line by putting each string at a given character column.

    Column geometry is the whole point of this parser, so fixtures state it
    explicitly rather than relying on hand-counted spaces.
    """
    line = ""
    for column, text in pieces:
        if len(line) > column:
            raise ValueError(f"column {column} already used by {line!r}")
        line = line.ljust(column) + text
    return line


def us_row(
    date: str, description: str, amount: str = "", balance: str = "", *, deposit: bool = False,
    amount_col: int = 119, deposit_col: int = 97, balance_col: int = 140,
) -> str:
    """One HSBC-US transaction line. Amounts are right-aligned to their columns;
    the balance carries a $ and the transaction amount does not."""
    pieces = [(0, date.ljust(16) if date else " " * 16), (16, description)]
    if amount:
        col = deposit_col if deposit else amount_col
        pieces.append((col - len(amount), amount))
    if balance:
        marked = f"${balance}"
        pieces.append((balance_col - len(marked), marked))
    return place(*pieces)


US_HEADER = [
    place((94, "DEPOSITS"), (104, "WITHDRAWALS")),
    place((0, "DATE"), (95, "& OTHER"), (105, "& OTHER")),
    place((0, "POSTED"), (16, "DESCRIPTION OF TRANSACTIONS"), (92, "ADDITIONS"),
          (104, "SUBTRACTIONS"), (126, "BALANCE")),
]

US_SUMMARY = [
    place((75, "ACCOUNT NUMBER 446-084310")),
    place((65, "STATEMENT PERIOD 01/07/25 TO 02/06/25")),
    place((0, "BEGINNING BALANCE"), (112, "$1,000.00")),
    place((1, "DEPOSITS & OTHER ADDITIONS"), (112, "$250.04")),
    place((1, "WITHDRAWALS & OTHER SUBTRACTIONS"), (112, "$180.00")),
    place((0, "ENDING BALANCE"), (112, "$1,070.04")),
]

US_FOOTER = [
    "Some of the payment information provided herein may be truncated due to space constraints.",
    place((64, "Page 1 of 2")),
]


def us_statement() -> str:
    """Two pages whose amount columns sit in different places — page 2 is
    shifted left by 22 characters, exactly as the real statements are."""
    page1 = [
        *US_SUMMARY,
        *US_HEADER,
        us_row("01/07/25", "OPENING BALANCE", balance="1,000.00"),
        us_row("01/08/25", "PURCHASE ON 0107 AT FLAT WHITE CAFE OXFORD", "40.00", "960.00"),
        us_row("", "GB"),  # trailing continuation line
        us_row("", "PURCHASE ON 0107 AT BOOK SHOP HIGH ST OXFORD", "60.00", "900.00"),
        place((80, "CONTINUED ON NEXT PAGE")),
        *US_FOOTER,
    ]
    shift = {"amount_col": 97, "deposit_col": 75, "balance_col": 118}
    page2 = [
        " CONTINUED FROM PREVIOUS PAGE",
        us_row("01/20/25", "WIRE TRANSFER FROM J NEFF", "250.00", "1,150.00",
               deposit=True, **shift),
        us_row("01/25/25", "PURCHASE ON 0124 AT EUR 45.00 RATE 1.1523 CAFE MILANO IT",
               "80.00", "1,070.00", **shift),
        us_row("02/06/25", "INTEREST PAID FROM 01/06/25 THRU 02/05/25", "0.04", "1,070.04",
               deposit=True, **shift),
        us_row("02/06/25", "ENDING BALANCE", balance="1,070.04", **shift),
        "                              All deposited items are credited subject to final payment.",
        place((64, "Page 2 of 2")),
    ]
    return FF.join(["\n".join(page1), "\n".join(page2)])


def us_multiline_statement() -> str:
    """A wire whose amount lands three lines below its description — the
    under-parsing failure mode that shows up as a large total discrepancy."""
    page = [
        place((0, "BEGINNING BALANCE"), (112, "$1,000.00")),
        place((1, "DEPOSITS & OTHER ADDITIONS"), (112, "$0.00")),
        place((1, "WITHDRAWALS & OTHER SUBTRACTIONS"), (112, "$500.00")),
        place((0, "ENDING BALANCE"), (112, "$500.00")),
        *US_HEADER,
        us_row("01/07/25", "OPENING BALANCE", balance="1,000.00"),
        us_row("01/09/25", "WIRE TRANSFER TO ACME LTD"),
        us_row("", "REF 8899201133"),
        us_row("", "EUR 420.00 RATE 1.1904"),
        us_row("", "BENEFICIARY ACME LTD LONDON", "500.00", "500.00"),
        "Some of the payment information provided herein may be truncated.",
    ]
    return "\n".join(page)


# --------------------------------------------------------------------------- #
# HSBC UK shape, built from the written reference profile
# --------------------------------------------------------------------------- #

def uk_row(
    date: str, code: str, description: str, paid_out: str = "", paid_in: str = "",
    balance: str = "",
) -> str:
    pieces = [(0, date.ljust(10) if date else " " * 10), (10, f"{code} {description}".strip())]
    if paid_out:
        pieces.append((71 - len(paid_out), paid_out))
    if paid_in:
        pieces.append((96 - len(paid_in), paid_in))
    if balance:
        pieces.append((121 - len(balance), balance))
    return place(*pieces)


UK_SUMMARY = [
    "Account Number 12345678",
    "Sheet Number 42",
    "Your Statement 01 January 2025 to 31 January 2025",
    place((0, "Opening Balance"), (40, "2,000.00")),
    place((0, "Payments In"), (40, "1,500.00")),
    place((0, "Payments Out"), (40, "700.00")),
    place((0, "Closing Balance"), (40, "2,800.00")),
]
UK_HEADER = place((0, "Date"), (10, "Payment type and details"), (60, "Paid out"),
                  (85, "Paid in"), (110, "Balance"))


def uk_statement(*, refund_as_purchase: bool = False) -> str:
    """A sterling statement. With `refund_as_purchase`, a VIS refund is money in
    even though VIS usually means money out — the case only the balance settles."""
    rows = [
        uk_row("01 Jan 25", "", "BALANCE BROUGHT FORWARD", balance="2,000.00"),
        uk_row("03 Jan 25", "DD", "BRITISH GAS", "200.00", balance="1,800.00"),
        uk_row("05 Jan 25", "CR", "SALARY ACME LTD", paid_in="1,500.00", balance="3,300.00"),
        uk_row("07 Jan 25", "VIS", "TESCO STORES 3456", "500.00", balance="2,800.00"),
    ]
    if refund_as_purchase:
        rows = [
            uk_row("01 Jan 25", "", "BALANCE BROUGHT FORWARD", balance="2,000.00"),
            uk_row("03 Jan 25", "DD", "BRITISH GAS", "200.00", balance="1,800.00"),
            uk_row("05 Jan 25", "CR", "SALARY ACME LTD", paid_in="1,500.00", balance="3,300.00"),
            # A refund: VIS, but money in. Its column says paid-in; its code says out.
            uk_row("06 Jan 25", "VIS", "TESCO REFUND 3456", paid_in="100.00", balance="3,400.00"),
            uk_row("07 Jan 25", "VIS", "TESCO STORES 3456", "600.00", balance="2,800.00"),
        ]
        summary = [
            r.replace("1,500.00", "1,600.00").replace("700.00", "800.00") for r in UK_SUMMARY
        ]
    else:
        summary = UK_SUMMARY
    return "\n".join([
        *summary, UK_HEADER, *rows,
        "Information about the Financial Services Compensation Scheme",
        "Interest rate 0.00% AER Gross",
    ])
