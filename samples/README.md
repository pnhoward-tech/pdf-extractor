Synthetic PDFs for trying the app out, regenerated with:

    python scripts/make_samples.py

They deliberately disagree with each other: the two invoices use different
header wording and different decimal conventions, and `survey_readings.pdf`
matches no profile at all so you can see passthrough mode.

`statements/` holds sample bank and card statements for the statement
extractor, rendered from the test fixtures in a monospace face so they behave
like real statements all the way through — including the reconciliation check.
All three balance. Drop them on <http://127.0.0.1:8000> to see the app work
without using your own financial data.
