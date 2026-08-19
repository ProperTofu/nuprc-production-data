#!/usr/bin/env python3
"""Turn NUPRC's monthly production PDF into the CSVs the terminal reads.

NUPRC publishes crude oil and condensate as a single cumulative PDF: the
July release carries January through July, not July alone. That shape is the
whole design. Every run rewrites the year's CSV from scratch rather than
appending a month, because NUPRC revises back months without announcement --
there is a "REVISED_JAN_-_MAY_BOPD" release sitting alongside the ordinary
ones -- and an append-only pipeline would keep the stale figures forever.
Rewriting is also what makes the script safe to run twice.

This script lives in the repo it writes to. The NUI Terminal reads these
CSVs over raw.githubusercontent and never produces them, so the pipeline
belongs here with its output rather than there with its consumer. Volumes are
stored as barrels per month, while the PDF publishes a daily rate in
thousands, so each value is multiplied by 1000 and by the length of that
month.

Both reports are handled, by two separate parsers behind --kind. They share
only the watermark handling, the download and the CSV writer, because the
reports have nothing else in common: crude is a terminal-by-terminal sheet
across two pages in thousand barrels per day, gas is one row per month
already in MMSCF.

PyMuPDF is the only dependency and is not worth installing permanently for a
script that runs once a month, so scripts/scrape_nuprc.sh runs this in a
throwaway container. Committing is left to that wrapper, which has git and a
checkout; this script only writes the file.

Usage:
    python scripts/scrape_nuprc.py --url <pdf-or-path> --year 2026
    python scripts/scrape_nuprc.py --url <pdf-or-path> --year 2026 --kind gas

Always pass the NEWEST release. Both reports are cumulative, so an older one
carries fewer months, and every run rewrites the whole year -- the guard for
that refuses to publish a year shorter than the one already committed.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import io
import logging
import re
import sys
import urllib.request
from pathlib import Path

logger = logging.getLogger("scrape_nuprc")

MONTHS = [m.upper() for m in calendar.month_name[1:]]
_MONTH_INDEX = {m: i + 1 for i, m in enumerate(MONTHS)}

# Only these two reach the CSV. "Blend Total" is a sum of the other two and
# would double-count the terminal if it were stored.
_EMITTED = ("Crude Oil", "Condensate")

# The NUPRC watermark is real text laid diagonally across the page, so table
# extraction drops whichever letter crosses a cell into that cell: "R\n4.37",
# "P\n62.31", "U\n-". Anchored on the newline because the letter is always its
# own text block. Matching a bare leading letter instead ate the "C" of
# "Crude Oil" and "Condensate" and silently dropped every row in the file.
_WATERMARK_RE = re.compile(r"^[NUPRC]\s*\n")

_UA = "Mozilla/5.0 (compatible; NUI-Terminal/1.0)"

# Every terminal and stream NUPRC has published in 2026. Checked rather than
# trusted, because a mangled name is the one failure this parser can produce
# that looks entirely normal downstream. The Jan-May release lays two labels
# over each other and extracts them interleaved, as "PUEGNON IONCGTON(JO S"
# and "CREEK)" -- PENNINGTON and UGO OCHA (JONES CREEK), with correct figures
# attached to nonsense names. Nothing else in the pipeline would notice.
#
# New streams are real (UTAPATE arrived this way), so an unknown name stops
# the run rather than being dropped, and --allow-new-terminals is how you say
# you have looked at it and it is genuinely new.
KNOWN_TERMINALS = frozenset({
    "ABO", "AGBAMI", "AJAPA", "AJE", "AKPO", "ANTAN", "ANYALA MADU (CJ Blend)",
    "BONGA", "BONNY", "BRASS", "CAWTHORNE", "EBOK", "EGINA", "ERHA",
    "ESCRAVOS (Oil Terminal)", "FORCADOS", "IMA", "NEMBE",
    "ODUDU (AMENAM BLEND)", "OKONO", "OKORO (Ex Ima Terminal)", "OKWORI",
    "OTAKPIPO", "OYO / OBODO", "PENNINGTON", "QUA IBOE", "SEA EAGLE (EA)",
    "TULJA - OKWUIBOME", "UGO OCHA (JONES CREEK)", "USAN", "UTAPATE", "YOHO",
})

# Rounding of the two-decimal per-terminal rates against NUPRC's own total.
# Observed worst case across seven months is 0.02 kb/d.
_TOTAL_TOLERANCE_KBD = 0.5



def _clean(value: object) -> str:
    if value is None:
        return ""
    return _WATERMARK_RE.sub("", str(value).strip()).replace("\n", " ").strip()


def _number(value: object) -> float | None:
    """A cell as a float, or None when NUPRC printed no figure.

    A dash means the stream did not produce that month. It is dropped rather
    than stored as zero: the existing CSVs omit those rows, and zero would
    read as a measured shutdown rather than an absence of data.
    """
    text = _clean(value).replace(",", "")
    if text in ("", "-", "–", "—"):
        return None
    try:
        return float(text)
    except ValueError:
        logger.warning("unparseable cell %r, skipped", text)
        return None


def parse_pdf(
    path: str | Path,
) -> tuple[list[tuple[str, str, dict[str, float | None]]], dict[str, float]]:
    """The terminal rows, and NUPRC's own national totals to check them against.

    Rows come back in document order, which is the order the CSVs already use.
    The totals are the "Daily Average / Total" line at the foot of page 2,
    read only so the terminal rows can be reconciled against a figure this
    parser did not derive.
    """
    import fitz  # PyMuPDF, installed into the throwaway container

    rows: list[list] = []
    published: dict[str, float] = {}
    with fitz.open(str(path)) as doc:
        for page in doc:
            for table in page.find_tables().tables:
                header: dict[int, str] | None = None
                for raw in table.extract():
                    cells = [_clean(c) for c in raw]
                    if cells[:2] == ["TERMINAL/STREAM", "Liquid Type"]:
                        # Column order is read from the header rather than
                        # assumed: the sheet carries all twelve months from
                        # January, with the unpublished ones dashed out.
                        header = {i: c for i, c in enumerate(cells) if c in MONTHS}
                        continue
                    if header is None:
                        continue
                    name, liquid = cells[0], cells[1]
                    # The foot of page 2. "Blend Total" is a terminal's own
                    # subtotal and is handled below; a bare "Total" is the
                    # national line, and the only figure here that this
                    # parser does not compute for itself.
                    if liquid == "Total":
                        published = {
                            m: v
                            for i, m in header.items()
                            if (v := _number(raw[i])) is not None
                        }
                        continue
                    # Blend Total is carried through grouping and dropped
                    # afterwards: it is one more row a merged terminal cell
                    # could have been attached to.
                    if liquid not in (*_EMITTED, "Blend Total"):
                        continue
                    # The national totals block at the foot of page 2 repeats
                    # the same liquid-type labels and would otherwise be read
                    # as a terminal called "Daily Average".
                    if name.startswith("Daily Average"):
                        continue
                    rows.append(
                        [name, liquid, {m: _number(raw[i]) for i, m in header.items()}]
                    )

    if not rows:
        raise ValueError(f"no production rows found in {path} -- is this the BOPD report?")

    # A merged terminal cell attaches to exactly one row of its group and the
    # others come back blank, but WHICH row varies: BONNY's name sits on its
    # middle row while every other triplet's sits on its first. So neither
    # carrying names down nor carrying them up is right on its own. Group the
    # rows first, then read the group's single name.
    #
    # A group opens at every Crude Oil row, and at a named Condensate row once
    # the open group already has a name -- that second rule is what keeps the
    # standalone condensate streams on page 2 (AGBAMI, AKPO, IMA) apart.
    def name_of(group: list[list]) -> str:
        return next((n for n, _, _ in group if n), "")

    groups: list[list[list]] = []
    current: list[list] = []
    for row in rows:
        name, liquid, _ = row
        if liquid == "Crude Oil" or (name and name_of(current)):
            if current:
                groups.append(current)
            current = []
        current.append(row)
    if current:
        groups.append(current)

    out: list[tuple[str, str, dict[str, float | None]]] = []
    for group in groups:
        terminal = name_of(group)
        if not terminal:
            logger.warning("group with no terminal name, skipped: %r", group)
            continue
        for _, liquid, values in group:
            if liquid == "Blend Total":
                continue
            out.append((terminal, liquid, values))
    return out, published


def check_terminals(rows: list[dict], allow_new: bool) -> None:
    """Stop on a terminal name NUPRC has not published before.

    This is the guard against a layout the parser reads confidently and
    wrongly: overlapping labels extract interleaved, so the figures stay
    right while the name they are filed under turns to nonsense, and every
    later stage accepts it.
    """
    unknown = sorted({r["terminal"] for r in rows} - KNOWN_TERMINALS)
    if not unknown:
        return
    for name in unknown:
        logger.warning("terminal not seen before: %r", name)
    if not allow_new:
        raise SystemExit(
            f"{len(unknown)} unrecognised terminal name(s): {unknown}\n"
            "Scrambled text extraction looks exactly like this. Open the PDF, "
            "and if the stream really is new, add it to KNOWN_TERMINALS or "
            "pass --allow-new-terminals."
        )


def reconcile(rows: list[dict], published: dict[str, float], year: int) -> None:
    """Check the summed terminal rows against NUPRC's printed national total.

    Catches a row dropped or counted twice, which the terminal-name check
    cannot see. It does not catch a misfiled name: the sum is the same
    whatever the rows are called, which is why both checks exist.
    """
    if not published:
        logger.warning("no national total row found; rows not reconciled")
        return
    for month, expected in sorted(published.items(), key=lambda kv: _MONTH_INDEX[kv[0]]):
        days = calendar.monthrange(year, _MONTH_INDEX[month])[1]
        got = sum(r["volume_bbls"] for r in rows if r["month"] == month) / 1000 / days
        if abs(got - expected) > _TOTAL_TOLERANCE_KBD:
            raise SystemExit(
                f"{month}: rows sum to {got:.2f} kb/d but NUPRC prints "
                f"{expected:.2f} kb/d. Refusing to publish."
            )
        logger.info("%s reconciles: %.2f kb/d", month, got)


def to_rows(parsed: list[tuple[str, str, dict]], year: int) -> list[dict]:
    """Flatten to CSV rows: a daily rate in thousands becomes barrels.

    A terminal keeps the position of its FIRST appearance even when a later
    page adds a liquid type to it, which is how TULJA - OKWUIBOME's condensate
    -- printed on page 2, away from its crude on page 1 -- lands beside its
    crude in the file. Values for a repeated (terminal, liquid, month) are
    summed, so the dashed blended-condensate row on page 1 contributes nothing
    and the real unblended figure on page 2 survives.
    """
    order: list[tuple[str, str]] = []
    totals: dict[tuple[str, str, str], float] = {}
    for terminal, liquid, values in parsed:
        key = (terminal, liquid)
        if key not in order:
            order.append(key)
        for month, rate in values.items():
            if rate is None:
                continue
            days = calendar.monthrange(year, _MONTH_INDEX[month])[1]
            cell = (terminal, liquid, month)
            totals[cell] = totals.get(cell, 0.0) + rate * 1000 * days

    # Deliberately unsorted: document order already IS the file's order, pair
    # by pair. Grouping each condensate under its terminal's crude looks tidier
    # and is wrong -- TULJA - OKWUIBOME's condensate belongs high in the file
    # because page 1 prints a (dashed) condensate row for it, while AJAPA has
    # no page 1 condensate row at all and so belongs down among page 2's
    # standalone streams. Sorting moved AJAPA and nothing else.
    rows = []
    for terminal, liquid in order:
        for month in MONTHS:
            value = totals.get((terminal, liquid, month))
            if value is None:
                continue
            rows.append(
                {
                    "month": month,
                    "terminal": terminal,
                    "liquid_type": liquid,
                    "volume_bbls": round(value, 1),
                }
            )
    return rows


def write_csv(rows: list[dict], path: Path) -> str:
    # newline="" and \n keep the file byte-identical to the existing ones
    # instead of introducing CRLF when this is run on Windows.
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=["month", "terminal", "liquid_type", "volume_bbls"],
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    text = buffer.getvalue()
    path.write_text(text, encoding="utf-8", newline="")
    return text


# ---------------------------------------------------------------- gas ------
#
# A different report and a different shape: one row per month, no terminals,
# already in the unit the CSV stores (MMSCF), so there is no rate-to-volume
# conversion and nothing to sum per terminal. It shares this file for the
# watermark handling, the fetch and the CSV writer, and nothing else.
#
# The published sheet carries three columns the CSV has never stored -- two
# percentages and gas shrinkage -- and they are dropped rather than added,
# both to keep the file's shape and because the percentages are unreliable:
# in the same October 2025 report, "% UTILIZED" is 92.0% for January but
# 0.93 for July, the same quantity written two ways. Utilisation is better
# recomputed from the volumes than trusted from that column.
_GAS_FIELDS = [
    ("ag_production_mmscf", ("AG PRODUCTION",)),
    ("nag_production_mmscf", ("NAG PRODUCTION",)),
    ("total_gas_produced_mmscf", ("TOTAL GAS PRODUCTION",)),
    ("field_use_mmscf", ("FIELD USE",)),
    ("domestic_sales_mmscf", ("DOMESTIC SALES",)),
    ("export_sales_mmscf", ("EXPORT SALES",)),
    ("total_gas_utilized_mmscf", ("TOTAL GAS UTILISED", "TOTAL GAS UTILIZED")),
    ("total_gas_flared_mmscf", ("TOTAL GAS FLARED",)),
]
GAS_COLUMNS = ["month"] + [name for name, _ in _GAS_FIELDS]

# The report's own TOTAL line is rounded to whole MMSCF while the months
# carry two decimals, so twelve months of rounding is the tolerance, not a
# fixed fraction.
_GAS_TOTAL_TOLERANCE = 12.0


def _norm_header(text: str) -> str:
    return re.sub(r"[^A-Z]", "", _clean(text).upper())


def parse_gas_pdf(path: str | Path) -> tuple[list[dict], dict[str, float]]:
    """Monthly gas rows, and the report's own TOTAL line to check them against.

    Columns are located by their headings rather than by position, so an
    inserted column does not silently shift every value one place left.
    """
    import fitz

    rows: list[dict] = []
    totals: dict[str, float] = {}
    with fitz.open(str(path)) as doc:
        for page in doc:
            for table in page.find_tables().tables:
                data = table.extract()
                column: dict[str, int] = {}
                for raw in data:
                    cells = [_clean(c) for c in raw]
                    if not column:
                        heads = [_norm_header(c) for c in cells]
                        for field, wanted in _GAS_FIELDS:
                            for want in wanted:
                                key = _norm_header(want)
                                hit = next(
                                    (i for i, h in enumerate(heads) if h.startswith(key)),
                                    None,
                                )
                                if hit is not None:
                                    column[field] = hit
                                    break
                        # Every field must be found, or the mapping is wrong
                        # and the values would be filed under the wrong names.
                        if len(column) != len(_GAS_FIELDS):
                            column = {}
                        continue

                    label = cells[0].upper()
                    values = {
                        field: _number(raw[i]) for field, i in column.items()
                    }
                    if label == "TOTAL":
                        totals = {f: v for f, v in values.items() if v is not None}
                        continue
                    if label not in MONTHS:
                        continue
                    # Months NUPRC has not published yet are blank or dashed
                    # across the row, and #DIV/0! in the percentage columns.
                    # They are skipped, not written as zero.
                    if all(v is None for v in values.values()):
                        continue
                    rows.append({"month": label, **values})

    if not rows:
        raise ValueError(
            f"no gas rows found in {path} -- is this the monthly gas publication?"
        )
    rows.sort(key=lambda r: _MONTH_INDEX[r["month"]])
    return rows, totals


def reconcile_gas(rows: list[dict], totals: dict[str, float]) -> None:
    """Check each column against the TOTAL line printed in the report."""
    if not totals:
        logger.warning("no TOTAL row found; gas columns not reconciled")
        return
    for field, expected in totals.items():
        got = sum(r[field] for r in rows if r.get(field) is not None)
        if abs(got - expected) > _GAS_TOTAL_TOLERANCE:
            raise SystemExit(
                f"{field}: months sum to {got:,.2f} but the report's TOTAL is "
                f"{expected:,.2f} MMSCF. Refusing to publish."
            )
    logger.info("all %d gas columns reconcile against the TOTAL row", len(totals))


def write_gas_csv(rows: list[dict], path: Path) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=GAS_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {k: ("" if row.get(k) is None else row.get(k)) for k in GAS_COLUMNS}
        )
    text = buffer.getvalue()
    path.write_text(text, encoding="utf-8", newline="")
    return text


def check_not_shrinking(rows: list[dict], path: Path, allow: bool) -> None:
    """Refuse to replace a published year with fewer months than it already has.

    Every run rewrites the whole year, which is what lets a revision to a back
    month land. The cost is that pointing the script at an OLDER release
    quietly deletes the months that release predates -- running the October
    2025 gas report over a finished 2025 would drop November and December,
    reconcile perfectly against its own TOTAL line, and look like a clean run.

    Nothing else can catch this: the file is internally consistent, just
    short. So the check is against what is already published, not against the
    PDF.
    """
    if not path.exists():
        return
    with path.open(newline="", encoding="utf-8") as handle:
        existing = {r["month"] for r in csv.DictReader(handle) if r.get("month")}
    missing = sorted(existing - {r["month"] for r in rows}, key=_MONTH_INDEX.get)
    if not missing:
        return
    logger.warning("%s already has months this report does not: %s",
                   path.name, ", ".join(missing))
    if not allow:
        raise SystemExit(
            f"{path.name} would lose {len(missing)} month(s): {', '.join(missing)}.\n"
            "This usually means an older report was passed. NUPRC's releases are "
            "cumulative, so use the newest one. Pass --allow-fewer-months only if "
            "you intend to publish a shorter year."
        )


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    # NUPRC's site is a Next.js app whose /reports/* path matches a dynamic
    # route, so a wrong or expired PDF link returns 200 with the HTML shell
    # rather than a 404. Without this check that page would be handed to the
    # PDF parser, which fails with something far less informative.
    if not data.startswith(b"%PDF"):
        raise ValueError(
            f"{url} returned {len(data)} bytes that are not a PDF "
            "(NUPRC serves its app shell with a 200 for unknown paths)"
        )
    return data




def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="PDF URL, or a local path")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument(
        "--kind",
        choices=("oil", "gas"),
        default="oil",
        help="which report this PDF is: crude and condensate, or monthly gas",
    )
    # Defaults to the repo root, two levels up from scripts/, so the CSV
    # lands beside the ones already published rather than in the caller's cwd.
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parent.parent),
        help="directory to write the CSV into",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would change, write nothing"
    )
    parser.add_argument(
        "--allow-fewer-months",
        action="store_true",
        help="permit rewriting a year with fewer months than it already has",
    )
    parser.add_argument(
        "--allow-new-terminals",
        action="store_true",
        help="accept terminal names not seen before (check the PDF first)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    source = Path(args.url)
    if source.exists():
        pdf_path = source
        temporary = None
    else:
        temporary = Path(args.out) / "_nuprc_download.pdf"
        temporary.write_bytes(fetch(args.url))
        pdf_path = temporary

    try:
        if args.kind == "gas":
            rows, gas_totals = parse_gas_pdf(pdf_path)
        else:
            parsed, published = parse_pdf(pdf_path)
            rows = to_rows(parsed, args.year)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()

    # Checks run before anything is written, so a bad parse cannot reach the
    # published CSVs, and from there every project that reads them.
    if args.kind == "gas":
        reconcile_gas(rows, gas_totals)
        logger.info("%d monthly gas rows", len(rows))
    else:
        check_terminals(rows, args.allow_new_terminals)
        reconcile(rows, published, args.year)
        logger.info(
            "%d rows, %d terminals", len(rows), len({r["terminal"] for r in rows})
        )

    months = sorted({r["month"] for r in rows}, key=lambda m: _MONTH_INDEX[m])
    logger.info("months %s to %s", months[0], months[-1])

    filename = f"{args.kind}_{args.year}.csv"
    if args.dry_run:
        logger.info("dry run, nothing written")
        for row in rows[:5]:
            print(",".join(str(v) for v in row.values()))
        return 0

    path = Path(args.out) / filename
    check_not_shrinking(rows, path, args.allow_fewer_months)
    if args.kind == "gas":
        write_gas_csv(rows, path)
    else:
        write_csv(rows, path)
    logger.info("wrote %s", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
