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
    """One HSBC UK line. Real statements put the code and payee on one line and
    the location and amount on the next, so most rows here carry no amount."""
    pieces = [(0, date.ljust(14) if date else " " * 14), (14, code.ljust(8)), (22, description)]
    if paid_out:
        pieces.append((71 - len(paid_out), paid_out))
    if paid_in:
        pieces.append((96 - len(paid_in), paid_in))
    if balance:
        pieces.append((121 - len(balance), balance))
    return place(*pieces)


# Spaced exactly as HSBC's own PDF kerning renders these labels.
UK_SUMMARY = [
    place((60, "Account Summary")),
    place((60, "Ope ning Balance"), (100, "£2,000 .00")),
    place((60, "Paym e nts In"), (100, "£1,500.00")),
    place((60, "Paym e nts Out"), (100, "£700.00")),
    place((60, "Clos ing Balance"), (100, "£2,800.00")),
    "30 June to 29 July 2026",
]
UK_ACCOUNT = [
    place((0, "Acco unt Nam e"), (60, "S o rtcode"), (75, "Acco unt Num ber"), (95, "S he e t Num be r")),
    place((0, "Philip Edward Howard & Mrs Gina Sue Neff"), (60, "40-35-34"), (75, "54027876"), (95, "858")),
    "Your Premier Bank Account details",
]
UK_HEADER = place((0, "Date"), (14, "Pay m e nt t y p e and de t ails"), (58, "£ Paid o ut"),
                  (83, "£ Paid in"), (108, "£ Balance"))


def uk_statement(*, refund_as_purchase: bool = False) -> str:
    """A sterling current account. With `refund_as_purchase`, a VIS refund is
    money in even though VIS usually means money out — the case only the
    balance settles."""
    rows = [
        uk_row("29 Jun 26", "", "BALANCE BROUGHT FORWARD", balance="2,000.00"),
        uk_row("30 Jun 26", "DD", "BRITISH GAS", "200.00"),
        # The amount arrives on the continuation line, as it usually does.
        uk_row("", "VIS", "SAINSBURYS S/MKTS"),
        uk_row("", "", "CAMBRIDGE", "500.00"),
        uk_row("01 Jul 26", "CR", "SALARY ACME LTD", paid_in="1,500.00", balance="2,800.00"),
    ]
    summary = UK_SUMMARY
    if refund_as_purchase:
        rows = [
            uk_row("29 Jun 26", "", "BALANCE BROUGHT FORWARD", balance="2,000.00"),
            uk_row("30 Jun 26", "DD", "BRITISH GAS", "200.00"),
            uk_row("01 Jul 26", "CR", "SALARY ACME LTD", paid_in="1,500.00"),
            # A refund: VIS, but money in. Its column says paid-in; its code says out.
            uk_row("", "VIS", "TESCO REFUND 3456", paid_in="100.00"),
            uk_row("", "VIS", "TESCO STORES 3456", "600.00", balance="2,800.00"),
        ]
        summary = [r.replace("£1,500.00", "£1,600.00").replace("£700.00", "£800.00")
                   for r in UK_SUMMARY]
    return "\n".join([
        *summary, *UK_ACCOUNT, UK_HEADER, *rows,
        "Info rmatio n abo ut the Financial S e rvice s Co mpe ns atio n Sche m e",
        "Cre dit Inte re s t Rate s   AER   0.00%",
    ])


# --------------------------------------------------------------------------- #
# HSBC UK credit card shape: two dates, one pre-signed amount column,
# no running balance, and columns that move between sheets.
# --------------------------------------------------------------------------- #

def card_row(
    posted: str, transacted: str, details: str, amount: str = "", *, credit: bool = False,
    amount_col: int = 94, details_col: int = 36,
) -> str:
    pieces = [(0, posted), (17, transacted), (details_col, details)]
    if amount:
        text = f"{amount}CR" if credit else amount
        pieces.append((amount_col - len(text), text))
    return place(*pieces)


CARD_SUMMARY = [
    place((62, "Account Summary")),
    place((62, "Credit Lim it"), (90, "£ 12,500.00")),  # HSBC's own kerning break
    place((62, "Previous Balance"), (90, "1,000.00")),
    place((62, "Debits"), (90, "250.00")),
    place((62, "Credits"), (90, "60.00")),
    place((62, "New Balance"), (90, "1,190.00")),
    place((0, "Statement Date 16 April 2024"), (60, "Sheet number 1 of 3")),
]


def card_statement() -> str:
    """Sheet 2 uses the fixture's default columns; sheet 3 shifts them right by
    27 characters, as the real statement's last sheet does."""
    page1 = [*CARD_SUMMARY, place((40, "DETACH HERE AND KEEP STATEM ENT"))]
    page2 = [
        place((0, "Statement Date 16 April 2024"), (60, "Sheet number 2 of 3")),
        place((0, "Your Transaction Details"), (85, "Amount")),
        place((0, "Received By Us"), (17, "Transaction Date"), (36, "Details")),
        card_row("16 Mar 24", "16 Mar 24", "Netflix.com     Los Gatos", "17.99"),
        card_row("18 Mar 24", "18 Mar 24", "Google Apps Mountain View CA", "6.05"),
        place((36, "7.70 USD@1.2727")),
        place((36, "MasterCard Exchange Rate")),
        card_row("18 Mar 24", "18 Mar 24", "NON-STERLING TRANSACTION FEE", "0.18"),
        card_row("27 Mar 24", "27 Mar 24", "UNIQLO EUROPE LTD  London", "50.00", credit=True),
        card_row("09 Apr 24", "09 Apr 24", "DIRECT DEBIT PAYMENT - THANK YOU", "10.00",
                 credit=True),
    ]
    shift = {"amount_col": 121, "details_col": 51}
    page3 = [
        place((0, "Statement Date 16 April 2024"), (60, "Sheet number 3 of 3")),
        card_row("13 Apr 24", "11 Apr 24", "SP INFOGRAPHICA  NORFOLK", "100.00", **shift),
        card_row("15 Apr 24", "15 Apr 24", "))) Coffee Bar Oxford", "108.20", **shift),
        place((0, "Summary Of Interest On This Statement")),
        place((36, "Interest on Standard Balance (Purchases) at 1.456% per month"), (105, "17.58")),
        place((36, "TOTAL INTEREST CHARGED ON THIS STATEM ENT"), (115, "17.58")),
        place((36, "Estimated interest - next month 171.22")),
        "We now provide m ore inform ation about the cost of using your card",
    ]
    return FF.join(["\n".join(page1), "\n".join(page2), "\n".join(page3)])
