#!/usr/bin/env python3
"""Turn NUPRC's rig disposition workbooks into two CSVs.

NUPRC publishes, monthly, every rig in the country: the contractor that owns
it, its name and type, the well it is standing on, the operator it is working
for, and what it is doing -- drilling, workover, completion, or stacked in a
yard. Nothing else here carries that.

It is also a different number from the Baker Hughes series in
rig_count_nigeria.csv, and the two must never be presented as versions of one
figure. Baker Hughes counts rigs ACTIVELY DRILLING; NUPRC counts every rig in
country. For January 2026 that is 15 against 72. The gap is long-standing:
Africa Oil+Gas Report put Baker Hughes at 9 for June 2014 against OPEC's 28
and the IADC Nigeria chapter's 23, and the IADC figure already excluded
workovers, so definition alone does not explain it.

Two outputs:
  rig_disposition_nigeria.csv  one row per rig per month
  rig_disposition_summary.csv  one row per month, counts by status

Layout notes, every one of them found by reading the files rather than
assuming:

- The header row moves: 13, 19, 20, 21 and 22 all occur across the sheets.
  Every table is therefore located by its heading text.

- Columns shift too. The 2026 workbook starts S/N at column 3, the earlier
  one at column 2.

- Each sheet holds THREE tables: RIG DISPOSITION, then VESSEL DISPOSITION,
  then Workover Hoists & Units. Reading to the end of the sheet merges all
  three -- 91 rows where the sheet's own total says 72 rigs -- so the rig
  table stops at the next heading.

- The status taxonomy changed. 2024 reports Active / Standby+Rig Move /
  Stacked; 2026 reports Active / Standby / Warm Stacked / Cold Stacked /
  Rig Move. The summary is read by its own column headings, not by position.

- Sheet names carry a typo ("FEBURARY_2026") and mix separators
  ("JANUARY 2024" against "JANUARY_2025"), so months are matched on their
  first three letters.

- Some sheets are present but blank -- November and December 2025 both carry
  dimensions and no content. They are skipped, never emitted as a month with
  zero rigs, which would read as the fleet having disappeared.

Every month is reconciled against the sheet's own "Rig Count ... Total" and
refuses to publish on a mismatch.

Usage:
    python scripts/scrape_rig_disposition.py                 # discover
    python scripts/scrape_rig_disposition.py --file a.xlsx   # local workbook
    python scripts/scrape_rig_disposition.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import urllib.request
from pathlib import Path

logger = logging.getLogger("rig_disposition")

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
REPORTS_API = "https://www.nuprc.gov.ng/api/report-pages"
FILES_API = "https://www.nuprc.gov.ng/api/files/"
_PAGE_TITLE = "rig disposition report"

DETAIL_CSV = "rig_disposition_nigeria.csv"
SUMMARY_CSV = "rig_disposition_summary.csv"

_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

# One rig either way is the source disagreeing with itself; more than
# that is this parser reading the wrong rows.
_RECONCILE_TOLERANCE = 1

# Fixed columns so the series means the same thing in every row. "stacked"
# survives alongside warm/cold because 2024 reports only the undivided figure.
_STATUS_COLUMNS = ("active", "standby", "rig_move", "warm_stacked",
                   "cold_stacked", "stacked")
# What the active rigs are actually doing. This is the OFS signal: drilling
# demand and workover demand are different markets, and the Baker Hughes
# series carries neither.
_ACTIVITY_COLUMNS = ("drilling", "workover", "completion", "well testing",
                     "wireline", "cementing")

_DETAIL_FIELDS = [
    "month", "rig_company", "rig_name", "rig_type", "location",
    "operating_company", "operational_status", "status_group", "activity",
    "licence_status",
]

# What the parenthesised part of a status is really saying. An OFS question
# cares which of these a rig is doing far more than it cares that the rig is
# "active": drilling demand and workover demand are different markets.
_ACTIVITIES = (
    ("workover", "workover"),
    ("re-completion", "completion"),
    ("recompletion", "completion"),
    ("completion", "completion"),
    ("drilling", "drilling"),
    ("cementing", "cementing"),
    ("wireline", "wireline"),
    ("logging", "logging"),
    ("dst", "well testing"),
    ("rig down", "rig down"),
    ("rig up", "rig up"),
    ("maintenance", "maintenance"),
)


# The heading that ends the rig table is spelled "VESSEL DIPOSITION" in the
# 2024 sheets -- no S -- and "VESSEL DISPOSITION" later. Matching the correct
# spelling alone ran the parser into the vessel table and collected three
# vessels plus the heading, putting every 2024 month exactly four rigs over
# the sheet's own total.
_NEXT_SECTION_RE = re.compile(r"VESSEL\s+DIS?POSITION|WORKOVER\s+HOIST")


def _norm(value: object) -> str:
    return " ".join(str(value or "").split())


def discover() -> list[tuple[str, str]]:
    """(title, url) for every rig disposition workbook NUPRC lists.

    Excel rather than PDF: the workbook carries a sheet per month, where the
    PDF is a rendering of the same thing that would have to be re-parsed out
    of page layout.
    """
    request = urllib.request.Request(REPORTS_API, headers={"User-Agent": _UA})
    with urllib.request.urlopen(request, timeout=45) as response:
        catalogue = json.load(response)

    out: list[tuple[str, str]] = []
    for page in catalogue.get("data") or []:
        if _norm(page.get("title")).lower() != _PAGE_TITLE:
            continue
        for doc in page.get("documents") or []:
            path = doc.get("excelUrl")
            title = _norm(doc.get("title"))
            # "Statistics" workbooks are the charts, not the register.
            if not path or "statistic" in title.lower():
                continue
            out.append((title, FILES_API + path))
    if not out:
        raise SystemExit(
            "no rig disposition workbooks in the NUPRC catalogue. It lists: "
            + ", ".join(_norm(p.get("title")) for p in (catalogue.get("data") or []))
        )
    return out


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(request, timeout=90) as response:
        data = response.read()
    # NUPRC's Next.js app answers an unknown path with its HTML shell and a
    # 200, so a stale link would otherwise reach the parser as "not a zip".
    if not data.startswith(b"PK"):
        raise ValueError(
            f"{url} returned {len(data)} bytes that are not an xlsx "
            "(NUPRC serves its app shell with a 200 for unknown paths)"
        )
    return data


def month_of(sheet_name: str) -> str | None:
    """'FEBURARY_2026' -> '2026-02'. None when the name is not a month."""
    text = _norm(sheet_name).upper().replace("_", " ")
    year = re.search(r"(20\d{2})", text)
    if not year:
        return None
    for token in re.findall(r"[A-Z]+", text):
        number = _MONTHS.get(token[:3])
        if number:
            return f"{year.group(1)}-{number:02d}"
    return None


def _find_row(ws, *needles: str, limit: int = 40) -> tuple[int, int] | None:
    """(row, column) of the first cell containing all these words."""
    for row in range(1, min(limit, ws.max_row) + 1):
        for col in range(1, min(20, ws.max_column) + 1):
            text = _norm(ws.cell(row, col).value).upper()
            if text and all(n.upper() in text for n in needles):
                return row, col
    return None


def parse_summary(ws) -> dict[str, int]:
    """The sheet's own status counts, read by their column headings.

    Never by position: 2024 has Active / Standby+Rig Move / Stacked and 2026
    has five buckets, so a fixed mapping silently mislabels one of them.
    """
    found = _find_row(ws, "RIG COUNT")
    if not found:
        return {}
    row, col = found
    out: dict[str, int] = {}
    # The headings sit on a row above the label, within a few rows.
    for back in range(1, 5):
        header_row = row - back
        if header_row < 1:
            break
        labels = {
            c: _norm(ws.cell(header_row, c).value)
            for c in range(col + 1, min(col + 12, ws.max_column + 1))
        }
        if not any(labels.values()):
            continue
        for c, label in labels.items():
            value = ws.cell(row, c).value
            if label and isinstance(value, (int, float)):
                key = label.lower().replace(" ", "_").replace("/", "_")
                out[key] = int(value)
        if out:
            break
    return out


def parse_rigs(ws, month: str) -> list[dict]:
    """The RIG DISPOSITION table only, stopping at the next section."""
    found = _find_row(ws, "RIG COMPANY")
    if not found:
        return []
    header_row, company_col = found
    cols = {}
    for c in range(company_col, min(company_col + 10, ws.max_column + 1)):
        label = _norm(ws.cell(header_row, c).value).upper()
        if "RIG COMPANY" in label:
            cols["rig_company"] = c
        elif "RIG NAME" in label:
            cols["rig_name"] = c
        elif "RIG TYPE" in label:
            cols["rig_type"] = c
        elif label == "LOCATION":
            cols["location"] = c
        elif "OPERATING COMPANY" in label:
            cols["operating_company"] = c
        elif "OPERATIONAL STATUS" in label:
            cols["operational_status"] = c
        elif "LICENCE STATUS" in label or "LICENSE STATUS" in label:
            cols["licence_status"] = c
    if "rig_company" not in cols or "operational_status" not in cols:
        return []

    rows: list[dict] = []
    blanks = 0
    for r in range(header_row + 1, ws.max_row + 1):
        company = _norm(ws.cell(r, cols["rig_company"]).value)
        # The vessel and workover tables follow this one; their headings sit
        # in the same column and would otherwise be read as rig names.
        joined = " ".join(
            _norm(ws.cell(r, c).value).upper()
            for c in range(1, min(12, ws.max_column + 1))
        )
        if _NEXT_SECTION_RE.search(joined):
            break
        if not company:
            blanks += 1
            if blanks >= 4:
                break
            continue
        blanks = 0
        if company.upper() in {"S/N", "RIG COMPANY"}:
            continue
        status = _norm(ws.cell(r, cols["operational_status"]).value)
        row = {
            "month": month,
            "rig_company": company,
            "rig_name": _norm(ws.cell(r, cols.get("rig_name", 0)).value) if cols.get("rig_name") else "",
            "rig_type": _norm(ws.cell(r, cols.get("rig_type", 0)).value) if cols.get("rig_type") else "",
            "location": _norm(ws.cell(r, cols.get("location", 0)).value) if cols.get("location") else "",
            "operating_company": _norm(ws.cell(r, cols.get("operating_company", 0)).value) if cols.get("operating_company") else "",
            "operational_status": status,
            "status_group": status_group(status),
            "activity": activity_of(status),
            "licence_status": _norm(ws.cell(r, cols.get("licence_status", 0)).value) if cols.get("licence_status") else "",
        }
        rows.append(row)
    return rows


def status_group(status: str) -> str:
    low = status.lower()
    if "cold" in low:
        return "cold stacked"
    if "warm" in low:
        return "warm stacked"
    if "stack" in low:
        return "stacked"
    if "move" in low:
        return "rig move"
    if "standby" in low or "stand by" in low:
        return "standby"
    if "active" in low:
        return "active"
    return status.lower() or "unknown"


def activity_of(status: str) -> str:
    low = status.lower()
    for needle, name in _ACTIVITIES:
        if needle in low:
            return name
    return ""


def parse_workbook(data: bytes, label: str) -> tuple[list[dict], list[dict], list[str]]:
    import io

    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    detail: list[dict] = []
    summary: list[dict] = []
    problems: list[str] = []

    for name in wb.sheetnames:
        month = month_of(name)
        if not month:
            continue
        ws = wb[name]
        rigs = parse_rigs(ws, month)
        if not rigs:
            # Blank sheets exist -- November and December 2025 both carry
            # dimensions and nothing else. Skipped, never emitted as a month
            # with no rigs, which would read as the fleet disappearing.
            logger.info("%s: %s is empty, skipping", label, name)
            continue

        counts = parse_summary(ws)
        stated = counts.get("total")
        gap = None if stated is None else stated - len(rigs)
        # A systematic offset means a parse fault and must stop the run: every
        # 2024 month was exactly four over until the misspelled "VESSEL
        # DIPOSITION" heading was matched. A difference of one is something
        # else -- August 2025's register ends at S/N 69 while its own summary
        # says 70 -- and that is the source disagreeing with itself. Recorded
        # on the row rather than silently dropped, and rather than costing a
        # whole month over one rig.
        if gap and abs(gap) > _RECONCILE_TOLERANCE:
            problems.append(
                f"{month}: parsed {len(rigs)} rigs but the sheet's total says {stated}"
            )
            continue

        detail.extend(rigs)
        # Counted from the register rather than copied from the sheet's own
        # buckets, which are not comparable across years: 2024 reports
        # "Standby/Rig Move" as one figure and 2026 splits them. A series has
        # to mean the same thing in every row of it.
        row = {"month": month, "rigs_listed": len(rigs), "stated_total": stated}
        by_group: dict[str, int] = {}
        for rig in rigs:
            by_group[rig["status_group"]] = by_group.get(rig["status_group"], 0) + 1
        for group in _STATUS_COLUMNS:
            row[group] = by_group.pop(group.replace("_", " "), 0)
        row["other"] = sum(by_group.values())
        by_activity: dict[str, int] = {}
        for rig in rigs:
            if rig["activity"]:
                by_activity[rig["activity"]] = by_activity.get(rig["activity"], 0) + 1
        for name in _ACTIVITY_COLUMNS:
            row["on_" + name] = by_activity.get(name, 0)
        if gap:
            row["source_discrepancy"] = (
                f"the sheet's own total says {stated}, its register lists {len(rigs)}"
            )
        summary.append(row)
        logger.info("%s: %s -> %d rigs%s", label, month, len(rigs),
                    f" (sheet says {stated})" if stated is not None else "")

    return detail, summary, problems


def write_csvs(out_dir: Path, detail: list[dict], summary: list[dict]) -> None:
    detail.sort(key=lambda r: (r["month"], r["rig_company"], r["rig_name"]))
    summary.sort(key=lambda r: r["month"])

    with open(out_dir / DETAIL_CSV, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_DETAIL_FIELDS)
        writer.writeheader()
        for row in detail:
            writer.writerow({k: row.get(k, "") for k in _DETAIL_FIELDS})

    keys = (["month", "rigs_listed", "stated_total"] + list(_STATUS_COLUMNS)
            + ["other"] + ["on_" + a for a in _ACTIVITY_COLUMNS]
            + ["source_discrepancy"])
    with open(out_dir / SUMMARY_CSV, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        for row in summary:
            writer.writerow({k: row.get(k, "") for k in keys})


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", action="append", default=[],
                    help="a local workbook instead of discovering; repeatable")
    ap.add_argument("--out", default=".", help="directory for the CSVs")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sources: list[tuple[str, bytes]] = []
    if args.file:
        for path in args.file:
            sources.append((Path(path).name, Path(path).read_bytes()))
    else:
        for title, url in discover():
            logger.info("fetching %s", title)
            sources.append((title, fetch(url)))

    detail: list[dict] = []
    summary: list[dict] = []
    problems: list[str] = []
    seen_months: set[str] = set()

    for label, data in sources:
        rows, months, issues = parse_workbook(data, label)
        problems.extend(issues)
        for row in months:
            # The workbooks overlap: the 2025 file carries 2024 months too.
            # Later files win, being the more recent publication.
            if row["month"] in seen_months:
                detail = [d for d in detail if d["month"] != row["month"]]
                summary = [s for s in summary if s["month"] != row["month"]]
            seen_months.add(row["month"])
        detail.extend(rows)
        summary.extend(months)

    if problems:
        for problem in problems:
            logger.error("RECONCILE %s", problem)
        raise SystemExit(
            f"{len(problems)} month(s) do not match the sheet's own rig total. "
            "Refusing to publish."
        )
    if not summary:
        raise SystemExit("no months parsed")

    months = sorted(s["month"] for s in summary)
    logger.info("%d rigs across %d months, %s to %s",
                len(detail), len(summary), months[0], months[-1])
    if args.dry_run:
        logger.info("dry run, nothing written")
        return 0

    write_csvs(Path(args.out), detail, summary)
    logger.info("wrote %s and %s", DETAIL_CSV, SUMMARY_CSV)
    return 0


if __name__ == "__main__":
    sys.exit(main())
