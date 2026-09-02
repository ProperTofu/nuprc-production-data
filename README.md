# nuprc-production-data

## Contents

| File | Source | Cadence |
|---|---|---|
| `oil_YYYY.csv` | NUPRC crude and condensate report | Monthly, published 11th-16th |
| `gas_YYYY.csv` | NUPRC monthly gas publication | Monthly, currently running later than oil |
| `rig_count_nigeria.csv` | **Baker Hughes** worldwide rig count | Monthly, first week of the following month |
| `nnpc_monthly_production.csv` | **NNPC Ltd** monthly report summary | Monthly, uploaded late in the following month |
| `nnpc_report_headline.csv` | **NNPC Ltd** monthly report summary | Monthly, one row per report |
| `nnpc_lifting_by_company.csv` | **NNPC Ltd** statutory disclosure | Quarterly, per company/field/month |
| `nnpc_lifting_cargoes.csv` | **NNPC Ltd** statutory disclosure | Quarterly, one row per cargo |
| `nnpc_production_by_field.csv` | **NNPC Ltd** statutory disclosure | Quarterly, per company/field/month |
| `nnpc_asset_equity.csv` | **NNPC Ltd** statutory disclosure | Quarterly, per block |

`scripts/` rebuilds all of them. `scrape_nuprc.py` discovers the newest NUPRC
report from the regulator's own catalogue; `scrape_rig_count.py` finds the
newest Baker Hughes workbook by filename, the download link carrying an opaque
id that changes each release; `scrape_nnpc_reports.py` reads NNPC's document
library and parses each monthly summary PDF.

### On the NNPC figures being different from NUPRC's

They are a second source, not a better one, and the two must not be merged.
Compared month by month for 2026:

- **Liquids agree.** NNPC's combined crude+condensate is within 0.03 mmbopd
  of the NUPRC total every month, with no consistent direction.
- **Gas does not.** NNPC is below NUPRC every single month, by 109 to 514
  mmscf/d — January 7,283 against 7,797, June 7,841 against 7,950. The sign
  never flips, so it is a difference of basis, not noise.

NUPRC publishes gas later than liquids, so NNPC is often the only source for
the most recent month: July 2026 gas is here at 7,489 while NUPRC has not
published July gas at all. **Do not use it to fill the NUPRC gap.** A figure
that runs 100–500 low, presented as the regulator's, is indistinguishable
from a correct one downstream. Report it as NNPC's or not at all.

Every NNPC page prints "All production, sales and financial figures are
provisional and subject to reconciliation with relevant stakeholders", and
that caveat is repeated in both CSV headers.

`financial_basis` in the headline CSV quotes the tile labels verbatim,
because their meaning shifts: statutory payments are cumulative year-to-date
(726 in January, 7,913 by July) even where the label says only "Statutory
Payments Feb". Differencing two of those gives a month; assuming they are
already monthly gives nonsense.

### The partner-lift column in NNPC's disclosure is misaligned

`nnpc_lifting_by_company.csv` reports `partner_lift_bbl` DERIVED as
`crude_volume_bbl - nnpc_equity_lift_bbl`. NNPC's own `Partner_Lift_bbl`
column is **not** used, and should not be.

In `NNPC_LTD_PRODUCTION_LIFTING_AND_GAS_DATA_Q1_2026` that column is correct
for the first block of the sheet and then shifts up by one row: from row 94
on, a company's cell holds the NEXT company's partner lift. Measured on
2026-09-02: 48 rows agree with their own arithmetic, 38 match the following
row instead. SNEPCO's 2,000,161 sits on TUPNI-EGINA's row; HEIRS' 124,000
sits on SEPLAT's. Read as published, companies are credited with a
neighbour's liftings — plausible numbers, wrong company, undetectable
downstream.

The derived figure is internally consistent for every row.
`partner_lift_source_disagreed` flags each row where NNPC's own cell
disagreed, so if they fix the workbook it will show.

### `nnpc_lifting_cargoes.csv` holds NNPC's SHARE of each cargo

The column is `nnpc_equity_lift_bbl`, not the size of the cargo. NNPC's
breakdown rows itemise their own equity lift, and they sum exactly to the
company's stated equity lift for the month (50,586,796 bbl across Q1 2026,
which is what the parser reconciles against). Pan Ocean's OML 147 cargo
moved 161,000 bbl of which NNPC's equity was 1,000 — the file records
1,000. Do not sum this column and call it liftings from those fields.

### What else is in those folders

The quarterly disclosure folders also hold NEPL's own-asset workbook (one
company, flat cargo list, published as "Copy of …" with the author's
`Working` tabs still in it and Q1 lifting dates reading 2026-09-01),
exploration registers, and commercial-arrangement workbooks. These are
skipped and listed, not parsed. **Every Q2 2026 file is listed by NNPC's CMS
but returns `BlobNotFound` from their CDN** — reported as UNAVAILABLE, and
it does not stop the readable quarters from being written.

### On the rig count being here

It is not NUPRC data, and this repo's name is narrower than its contents. It
lives here anyway because this is the repo that is **public**, and everything
that reads these files at runtime does so over `raw.githubusercontent`, which
returns 404 for a private repo. The Baker Hughes workbooks it is built from
are archived in `NUI-Terminal-Sources` alongside the other source documents.

Baker Hughes publish the rig count as a public service and ask to be credited.
Anything reporting these figures should say where they came from. NUPRC
publish rig disposition too, but quarterly and late, which is why this series
is used instead.

**Nigeria runs between 5 and 20 rigs, so month-on-month percentages mislead** —
offshore stood at 0 in May 2025 and fell from 5 to 1 in April 2026. Quote
absolute changes month to month; percentages only over a longer span.
