#!/usr/bin/env python3
"""Turn NNPC Ltd's monthly report PDFs into CSVs, and watch for new ones.

NNPC publishes a one-page summary every month at nnpcgroup.com/documents,
under "<year> Documents" / "<year> Monthly Reports". Each page carries a
twelve-month history, so one download backfills a whole year and a monthly
run mostly re-confirms what is already here.

WHAT THIS IS NOT
----------------
These are NNPC's OWN figures and they are not NUPRC's. Do not merge them
with oil_YYYY.csv or gas_YYYY.csv, and never present a figure from here as
a regulator number:

- NNPC reports crude AND condensate together as one headline (1.68 mmbopd
  for July 2026). NUPRC publishes crude and condensate separately. The split
  is captured here as crude_mmbopd and condensate_mmbopd precisely so
  nobody has to guess which basis a comparison is on.
- Every page prints "All production, sales and financial figures are
  provisional and subject to reconciliation with relevant stakeholders."
  That caveat travels with the numbers; it is written into the CSV header
  comment and should reach any reader who sees them.

MEASURED AGAINST NUPRC, 2026 (this repo's oil_2026.csv and gas_2026.csv,
compared month by month on 2026-09-02):

- LIQUIDS AGREE. NNPC's crude+condensate sits within 0.03 mmbopd of the
  NUPRC total every month, about one to two percent, no consistent
  direction. Treat them as the same quantity measured twice.
- GAS DOES NOT. NNPC is BELOW NUPRC every single month, by 109 to 514
  mmscf/d: January 7,283 against 7,797, June 7,841 against 7,950. The sign
  never flips, so this is a difference of basis and not noise -- NNPC is
  not reporting the national total the way NUPRC does. A NNPC gas figure
  must never be presented as a national one, and the two must never be
  charted as one series.

The gas gap is also the temptation. NUPRC publishes gas later than liquids,
so NNPC will often be the ONLY source for the most recent month -- July 2026
is here at 7,489 mmscf/d while NUPRC has not published July gas at all.
Filling a NUPRC gap with a number that runs 100-500 low is exactly the
fabrication this project keeps finding: right shape, wrong provenance,
impossible to spot downstream. Report it as NNPC's figure or not at all.

The same rule the NEITI and Baker Hughes data live under: a second source is
only worth having if it stays visibly a second source.

WHAT IT EXTRACTS
----------------
nnpc_monthly_production.csv   one row per month, from the twelve-month
                              series: crude+condensate, the crude and
                              condensate split, gas production, gas sales
nnpc_report_headline.csv      one row per report: revenue, profit after tax,
                              statutory payments year-to-date, and the AKK
                              and OB3 pipeline completion percentages
nnpc_reports_manifest.json    every document seen, with its published date
                              and checksum -- this is what makes a new
                              report detectable rather than merely present

RECONCILIATION
--------------
The page checks itself, and this refuses to publish when it does not:

- the headline gas figure must equal the last month of the gas series
- the headline crude+condensate figure must equal the last month of its
  series
- crude + condensate must equal the combined figure, every month

A layout change that silently shifted a column would break all three rather
than quietly emit wrong numbers, which is the failure this is guarding
against. Nothing is written when a check fails.

ON ROBOTS.TXT
-------------
nnpcgroup.com serves "User-agent: * / Disallow: /" -- the blanket default
Nuxt emits when a site is marked non-indexable, not a considered rule about
these documents, which NNPC publishes for the public to read. It is still a
stated preference, so this is deliberately the lightest thing that works:
ONE listing request per run, one download only when a document is new, an
honest User-Agent naming the project, and no crawling of anything else on
the site. Run it monthly. If NNPC ever asks for it to stop, that is the end
of the discussion and this script comes out.

Usage:
    python scripts/scrape_nnpc_reports.py                  # current year
    python scripts/scrape_nnpc_reports.py --year 2025
    python scripts/scrape_nnpc_reports.py --dry-run
    python scripts/scrape_nnpc_reports.py --file report.pdf
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("nnpc")

# Names the project rather than pretending to be a browser. The other
# scrapers here send a browser string because the sites they read reject
# anything else; nothing on nnpcgroup.com does, so there is no reason not to
# say who this is. No contact address: that is the repo owner's to give, not
# this script's to leak into someone else's access log.
_UA = ("NUI-Terminal-DocWatch/1.0 "
       "(+https://github.com/ProperTofu/nuprc-production-data)")

_SITE = "https://www.nnpcgroup.com"
_TIMEOUT = 60

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# The disclosure printed on every page. Carried into the CSVs so a reader of
# the data sees what a reader of the PDF sees.
_PROVISIONAL = ("NNPC Ltd's own figures, provisional and subject to "
                "reconciliation. Not NUPRC data -- do not merge.")


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.read()


def _unescape(html: str) -> str:
    """Nuxt embeds its payload with escaped slashes in JSON strings."""
    return html.replace(chr(92) + "u002F", "/").replace(chr(92) + "/", "/")


def discover(year: int) -> list[dict]:
    """Every monthly report published for `year`, newest first.

    One request. The folder listing is server-rendered, so the document
    URLs, display names and upload timestamps are all in the HTML -- there
    is no need to walk into each document or call the CMS API.
    """
    folder = f"{_SITE}/documents/{year}%20Documents/{year}%20Monthly%20Reports"
    try:
        html = _unescape(_fetch(folder).decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            logger.warning("no %s monthly reports folder (%s)", year, exc)
            return []
        raise

    # Paths carry a Strapi hash -- NNPC_Monthly_Report_May_2026_cdc0edb39f
    # -- so they cannot be constructed from a month name and must be read
    # from the listing. That hash is also why a renamed re-upload looks like
    # a new document, which is correct: it is a new file.
    paths = sorted(set(re.findall(r"/uploads/[A-Za-z0-9._%-]+.pdf", html)))
    stamps = re.findall(r"(20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d)", html)
    published = max(stamps) if stamps else ""

    out = []
    for path in paths:
        name = path.rsplit("/", 1)[-1]
        month = _month_from_name(name)
        out.append({
            "document": name,
            "url": _CDN + path if not path.startswith("http") else path,
            "month": month,
            "listing_published": published,
        })
    out.sort(key=lambda d: d["month"] or "", reverse=True)
    return out


# Strapi serves the files from its Azure front door, not from the site host.
_CDN = "https://fde-nnpc-web-cms-prod-dwfrd0hraahrbhhg.a02.azurefd.net"


def _month_from_name(name: str) -> str:
    """'NNPC_Monthly_Report_May_2026_cdc0edb39f.pdf' -> '2026-05'.

    Filenames are not a stable format -- January arrived as "ver 5", March
    as "_v1", July as "for July 2026" -- so this reads a month name and a
    year out of the text rather than matching a shape. The month is
    confirmed against the PDF's own title before anything is written; this
    is only for ordering and for reporting what was found.
    """
    low = name.lower()
    year = re.search(r"(20\d\d)", low)
    for token, num in _MONTHS.items():
        if re.search(rf"[_ -]{token}", low):
            if year:
                return f"{year.group(1)}-{num:02d}"
    return ""


def _numeric(line: str) -> float | None:
    s = line.strip().replace(",", "").rstrip("%")
    if not s or not re.fullmatch(r"-?\d+(\.\d+)?", s):
        return None
    return float(s)


def _after(lines: list[str], pattern: str) -> tuple[float | None, str]:
    """The first number after a label line, with the label that matched.

    The layout is a grid of tiles, and pymupdf reads each tile as its label
    lines followed by its value. Matching the label and taking the next
    number survives the tiles being reordered -- which they are: January
    leads with the Foundation narrative and July leads with production.

    A REGEX, not a substring, because the tiles are relabelled month to
    month: "Revenue (NGN Billion)" in July is "Revenue - Jan (NGN Billion)"
    in January, and a substring match for the former silently returns None
    for the latter -- an empty column rather than a failure.

    The matched label comes back with the value because it carries meaning
    the number does not. January's "Statutory Payments / Jan" is one month;
    July's "Statutory Payments Jan to July" is seven of them cumulative.
    Recording which was read beats asserting a basis this cannot verify.
    """
    rx = re.compile(pattern, re.I)
    for i, line in enumerate(lines):
        if rx.search(line):
            # The label may wrap ("Statutory Payments" / "Jan (NGN Billion)"),
            # so gather the label lines up to the number.
            label = [line.strip()]
            for j in range(i + 1, min(i + 4, len(lines))):
                value = _numeric(lines[j])
                if value is not None:
                    return value, " ".join(label)
                label.append(lines[j].strip())
    return None, ""


def _series(lines: list[str], title: str) -> tuple[list[str], list[list[float]]]:
    """A charted series: its month labels, then its stacked value groups.

    Returns (months, groups). The crude chart stacks three groups of twelve
    -- the combined figure, then crude, then condensate -- and the gas chart
    carries one. Reading whatever number of complete groups follows keeps
    both working, and keeps working if NNPC stacks a third component.
    """
    for i, line in enumerate(lines):
        if line.strip().lower() != title.lower():
            continue
        months, j = [], i + 1
        while j < len(lines):
            m = re.fullmatch(r"([A-Za-z]{3})-(\d\d)", lines[j].strip())
            if not m:
                break
            months.append(f"20{m.group(2)}-{_MONTHS[m.group(1).lower()]:02d}")
            j += 1
        if not months:
            continue
        values = []
        while j < len(lines):
            value = _numeric(lines[j])
            if value is None:
                break
            values.append(value)
            j += 1
        groups = [values[k:k + len(months)]
                  for k in range(0, len(values) - len(months) + 1, len(months))]
        return months, groups
    return [], []


def parse(pdf_bytes: bytes, document: str) -> dict:
    import pymupdf

    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        text = "".join(page.get_text() for page in doc)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ValueError(f"{document}: no text layer -- a scan, not a report")

    title = lines[0]
    m = re.search(r"([A-Za-z]+)\s+(20\d\d)", title)
    if not m or m.group(1)[:3].lower() not in _MONTHS:
        raise ValueError(f"{document}: cannot read a month from title {title!r}")
    report_month = f"{m.group(2)}-{_MONTHS[m.group(1)[:3].lower()]:02d}"

    gas_months, gas_groups = _series(lines, "Gas Production (mmscf/d)")
    oil_months, oil_groups = _series(lines, "Crude Oil & Condensate Production (mmbopd)")
    sales_months, sales_groups = _series(lines, "Gas Sales (mmscf/d)")
    if not gas_groups or not oil_groups:
        raise ValueError(f"{document}: production series missing -- layout changed")

    revenue, revenue_label = _after(lines, r"revenue.*NGN Billion")
    pat, pat_label = _after(lines, r"profit after tax")
    statutory, statutory_label = _after(lines, r"statutory payments")
    combined, _ = _after(lines, r"crude oil & condensate production")
    gas_headline, _ = _after(lines, r"natural gas production")
    akk, _ = _after(lines, r"^\s*AKK\s*$")
    ob3, _ = _after(lines, r"^\s*OB3\s*$")

    rows: dict[str, dict] = {}
    for month, value in zip(gas_months, gas_groups[0]):
        rows.setdefault(month, {})["gas_production_mmscfd"] = value
    for month, value in zip(sales_months, sales_groups[0] if sales_groups else []):
        rows.setdefault(month, {})["gas_sales_mmscfd"] = value

    crude, condensate = _split_oil(oil_groups, oil_months, report_month,
                                   combined, document)
    for month, value in zip(oil_months, crude):
        rows.setdefault(month, {})["crude_mmbopd"] = value
    for month, value in zip(oil_months, condensate):
        rows.setdefault(month, {})["condensate_mmbopd"] = value
    for month, c, k in zip(oil_months, crude, condensate):
        rows[month]["crude_condensate_mmbopd"] = round(c + k, 2)

    headline = {
        "report_month": report_month,
        "revenue_ngn_bn": revenue,
        "profit_after_tax_ngn_bn": pat,
        "statutory_payments_ngn_bn": statutory,
        "akk_completion_pct": akk,
        "ob3_completion_pct": ob3,
        "crude_condensate_mmbopd": combined,
        "gas_production_mmscfd": gas_headline,
        # What those three financial figures actually cover, quoted from the
        # page. The basis changes between reports and the numbers do not say
        # so: 726 is one month of statutory payments, 7,913 is seven.
        "financial_basis": " | ".join(
            x for x in (revenue_label, pat_label, statutory_label) if x),
        "document": document,
    }
    _reconcile(report_month, rows, headline, document)
    return {"report_month": report_month, "rows": rows, "headline": headline}


def _split_oil(groups: list[list[float]], months: list[str], report_month: str,
               combined: float | None, document: str) -> tuple[list, list]:
    """Pull crude and condensate out of the stacked oil chart.

    The chart is not drawn the same way every month. January stacks two
    series, crude then condensate, and prints no total. July stacks three,
    leading with the combined figure. Reading by position alone would have
    filed January's crude as a combined total and its condensate as crude --
    a 1.39 reported where 1.64 belongs, with nothing to signal it.

    So the shape is IDENTIFIED rather than assumed, by testing each
    candidate against the total NNPC printed in its headline tile. The
    combined figure is then always recomputed from the two components, which
    is what makes the reconciliation in _reconcile a real check rather than
    a comparison of a number with itself.
    """
    if combined is None:
        raise ValueError(f"{document}: no combined production headline to test against")
    try:
        at = months.index(report_month)
    except ValueError:
        raise ValueError(
            f"{document}: report month {report_month} absent from the oil chart")

    # Try every adjacent pair, newest layout first: three series means the
    # components are the last two, two series means they are the only two.
    for first in range(len(groups) - 1):
        crude, cond = groups[first], groups[first + 1]
        if len(crude) <= at or len(cond) <= at:
            continue
        if abs((crude[at] + cond[at]) - combined) <= 0.016:
            return crude, cond
    raise ValueError(
        f"{document}: no pair of series in the oil chart adds to the headline "
        f"{combined} for {report_month} -- chart layout changed")


def _reconcile(report_month: str, rows: dict, headline: dict, document: str) -> None:
    """Check the page against itself. Raise rather than publish a mismatch.

    Every one of these compares two numbers NNPC printed independently, so a
    disagreement means this script misread the page -- a tile reordered, a
    series gaining a component, a column shifting. That is worth failing a
    run for. It is not worth guessing at.
    """
    month = rows.get(report_month)
    if not month:
        raise ValueError(
            f"{document}: report month {report_month} absent from its own series")

    checks = [
        ("gas", month.get("gas_production_mmscfd"),
         headline.get("gas_production_mmscfd"), 1.0),
        ("crude+condensate", month.get("crude_condensate_mmbopd"),
         headline.get("crude_condensate_mmbopd"), 0.011),
    ]
    for name, series_value, headline_value, tolerance in checks:
        if series_value is None or headline_value is None:
            raise ValueError(f"{document}: {name} missing from headline or series")
        if abs(series_value - headline_value) > tolerance:
            raise ValueError(
                f"{document}: {name} headline {headline_value} does not match "
                f"the series' {report_month} value {series_value}")

    # Every month must carry both components. A chart read half-correctly
    # would otherwise publish a crude series with condensate missing.
    for m, values in sorted(rows.items()):
        if "crude_mmbopd" in values and "condensate_mmbopd" not in values:
            raise ValueError(f"{document}: {m} has crude but no condensate")


def _check_statutory_basis(headlines: dict) -> None:
    """Warn if statutory payments stop looking cumulative.

    The labels are inconsistent -- January and February print "Statutory
    Payments Jan" and "Statutory Payments Feb", March onward "Jan to Mar" --
    but the figures run 726, 1,804, 2,888, 3,714, 4,858, 6,286, 7,913 across
    2026, which only reads as year-to-date. The early labels are abbreviated,
    not a different basis.

    That inference is worth stating and worth testing, because someone will
    eventually difference two of these to get a month and be wrong by a year.
    A WARNING rather than a refusal: if NNPC genuinely switches to monthly
    reporting the numbers stop rising, and that is news about the source,
    not a broken parse. The run should still publish, loudly.
    """
    by_year: dict[str, list[tuple[str, float]]] = {}
    for month, headline in sorted(headlines.items()):
        value = headline.get("statutory_payments_ngn_bn")
        if value is not None:
            by_year.setdefault(month[:4], []).append((month, value))
    for year, series in by_year.items():
        for (prev_m, prev), (this_m, this) in zip(series, series[1:]):
            if this < prev:
                logger.warning(
                    "statutory payments fell from %s (%s) to %s (%s) -- the "
                    "year-to-date basis may have changed; check the labels "
                    "in nnpc_report_headline.csv before differencing these",
                    prev, prev_m, this, this_m)


def _load_manifest(out: Path) -> dict:
    path = out / "nnpc_reports_manifest.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict], note: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(f"# {note}\n")
        # An explicit LF terminator. csv.writer defaults to CRLF on EVERY
        # platform, so the data rows came out CRLF while the comment line
        # above them was LF. Git on Windows strips the CR going into the
        # index and Linux does not, so a laptop and the VM each rewrote the
        # other's version forever: one churn commit per run, 349 lines
        # changed and not a figure different. Same fix as scrape_nuprc.py,
        # whose own note says it keeps the file byte-identical.
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=datetime.now(timezone.utc).year)
    ap.add_argument("--out", default=".")
    ap.add_argument("--file", help="parse a local PDF instead of downloading")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    out = Path(args.out)
    manifest = _load_manifest(out)

    if args.file:
        blob = Path(args.file).read_bytes()
        found = [{"document": Path(args.file).name, "url": "", "month": "",
                  "listing_published": ""}]
        blobs = {found[0]["document"]: blob}
    else:
        found = discover(args.year)
        if not found:
            logger.info("no monthly reports found for %s", args.year)
            return 0
        blobs = {}

    new = [d for d in found if d["document"] not in manifest]
    logger.info("%s report(s) listed for %s, %s new",
                len(found), args.year, len(new))
    for d in new:
        logger.info("  NEW  %s", d["document"])

    # Parse every listed report, not only the new ones: each carries twelve
    # months, and a re-upload ("ver 5", "_v1") revises figures already
    # published. Rebuilding from all of them makes a correction arrive
    # instead of being masked by the row already sitting in the CSV.
    parsed, failures = [], []
    for d in found:
        try:
            blob = blobs.get(d["document"]) or _fetch(d["url"])
        except Exception as exc:
            failures.append(f"{d['document']}: download failed ({exc})")
            continue
        try:
            result = parse(blob, d["document"])
        except Exception as exc:
            failures.append(str(exc))
            continue
        result["digest"] = hashlib.sha256(blob).hexdigest()[:16]
        result["meta"] = d
        parsed.append(result)

    if failures:
        for f in failures:
            logger.error("REFUSED %s", f)
        # Nothing is written on any failure. A partial rebuild would drop
        # the months belonging to the report that failed, and a shorter CSV
        # reads as "NNPC stopped publishing" rather than as a broken parse.
        return 1
    if not parsed:
        logger.info("nothing parsed")
        return 0

    # Oldest first, so a later report's revision of a month wins.
    parsed.sort(key=lambda r: r["report_month"])
    production: dict[str, dict] = {}
    headlines: dict[str, dict] = {}
    for result in parsed:
        for month, values in result["rows"].items():
            row = production.setdefault(month, {"month": month})
            row.update(values)
            row["source_report"] = result["headline"]["document"]
        headlines[result["report_month"]] = result["headline"]

    _check_statutory_basis(headlines)

    if args.dry_run:
        for month in sorted(production)[-14:]:
            logger.info("  %s  %s", month, production[month])
        for month in sorted(headlines):
            logger.info("  headline %s  %s", month, headlines[month])
        return 0

    _write_csv(
        out / "nnpc_monthly_production.csv",
        ["month", "crude_condensate_mmbopd", "crude_mmbopd", "condensate_mmbopd",
         "gas_production_mmscfd", "gas_sales_mmscfd", "source_report"],
        [production[m] for m in sorted(production)],
        _PROVISIONAL,
    )
    _write_csv(
        out / "nnpc_report_headline.csv",
        ["report_month", "revenue_ngn_bn", "profit_after_tax_ngn_bn",
         "statutory_payments_ngn_bn", "akk_completion_pct",
         "ob3_completion_pct", "crude_condensate_mmbopd",
         "gas_production_mmscfd", "financial_basis", "document"],
        [headlines[m] for m in sorted(headlines)],
        _PROVISIONAL,
    )

    seen = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for result in parsed:
        meta = result["meta"]
        entry = manifest.get(meta["document"], {})
        manifest[meta["document"]] = {
            "url": meta["url"],
            "report_month": result["report_month"],
            "digest": result["digest"],
            "first_seen": entry.get("first_seen", seen),
            "listing_published": meta.get("listing_published", ""),
        }
    with open(out / "nnpc_reports_manifest.json", "w", encoding="utf-8") as f:
        json.dump(dict(sorted(manifest.items())), f, indent=2)
        f.write("\n")

    logger.info("wrote %s months and %s report headlines",
                len(production), len(headlines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
