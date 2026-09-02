# nuprc-production-data

## Contents

| File | Source | Cadence |
|---|---|---|
| `oil_YYYY.csv` | NUPRC crude and condensate report | Monthly, published 11th-16th |
| `gas_YYYY.csv` | NUPRC monthly gas publication | Monthly, currently running later than oil |
| `rig_count_nigeria.csv` | **Baker Hughes** worldwide rig count | Monthly, first week of the following month |
| `nnpc_monthly_production.csv` | **NNPC Ltd** monthly report summary | Monthly, uploaded late in the following month |
| `nnpc_report_headline.csv` | **NNPC Ltd** monthly report summary | Monthly, one row per report |

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
