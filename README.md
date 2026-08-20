# nuprc-production-data

## Contents

| File | Source | Cadence |
|---|---|---|
| `oil_YYYY.csv` | NUPRC crude and condensate report | Monthly, published 11th-16th |
| `gas_YYYY.csv` | NUPRC monthly gas publication | Monthly, currently running later than oil |
| `rig_count_nigeria.csv` | **Baker Hughes** worldwide rig count | Monthly, first week of the following month |

`scripts/` rebuilds all three. `scrape_nuprc.py` discovers the newest NUPRC
report from the regulator's own catalogue; `scrape_rig_count.py` finds the
newest Baker Hughes workbook by filename, the download link carrying an opaque
id that changes each release.

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
