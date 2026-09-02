#!/usr/bin/env python3
"""Turn NNPC's statutory disclosure workbooks into CSVs.

These are the disclosures NNPC publish under nnpcgroup.com/documents, and
they carry what the monthly report summary does not: production and liftings
COMPANY BY COMPANY and FIELD BY FIELD, cargo by cargo, with the buyer and
destination of each lifting.

Four outputs:

  nnpc_lifting_by_company.csv   one row per company/field/month: crude
                                volume, NNPC's equity lift, and the partner
                                lift DERIVED from the two (see the warning
                                below -- do not use the published column)
  nnpc_lifting_cargoes.csv      one row per cargo: date, volume, cargo id,
                                buyer, destination, export or domestic
  nnpc_production_by_field.csv  one row per company/field/month: crude,
                                condensate, gas, LPG, total BOE, daily average
  nnpc_asset_equity.csv         contract type, operator, NNPC equity and
                                partners for each OML/PML block

THE PUBLISHED PARTNER-LIFT COLUMN IS MISALIGNED. DO NOT READ IT.
----------------------------------------------------------------
In NNPC_LTD_PRODUCTION_LIFTING_AND_GAS_DATA_Q1_2026, column G
(Partner_Lift_bbl) is correct for the first block of the sheet and then
shifts up by exactly one row: from row 94 onward, a company's G cell holds
the NEXT company's partner lift. Measured across the sheet on 2026-09-02:
48 rows where G equals that row's own crude minus equity lift, 38 where it
equals the FOLLOWING row's. SNEPCO's 2,000,161 sits on TUPNI-EGINA's row;
HEIRS' 124,000 sits on SEPLAT's.

Read as published, every affected company is credited with a neighbour's
partner lift -- plausible magnitudes, wrong company, and nothing downstream
could tell. So partner lift is DERIVED here as crude_volume minus
nnpc_equity_lift, which is internally consistent for every row in the sheet,
and column G is never published. `partner_lift_source_disagreed` records
whether NNPC's own cell agreed, so the day they fix the workbook is visible
rather than silent.

This is NNPC's data about NNPC-interest assets (the JVs and PSCs where
NNPC/NUIMS holds equity). It is not a national total and it is not NUPRC's;
see the README, and [do not] merge it with oil_YYYY.csv or gas_YYYY.csv.

FORMAT CHANGED IN 2026. 2025 was published as MONTHLY disclosures -- four
separate workbooks a month, including a NUPRC crude-oil lifting cargo list
and a production profile by field. 2026 moved to QUARTERLY disclosures with
a single multi-sheet workbook per entity. This script reads the 2026
quarterly form. The 2025 monthly form is a different shape and is not read
yet.

Usage:
    python scripts/scrape_nnpc_disclosures.py                 # current year
    python scripts/scrape_nnpc_disclosures.py --year 2026
    python scripts/scrape_nnpc_disclosures.py --dry-run
    python scripts/scrape_nnpc_disclosures.py --file book.xlsx
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

logger = logging.getLogger("nnpc-disclosures")

_UA = ("NUI-Terminal-DocWatch/1.0 "
       "(+https://github.com/ProperTofu/nuprc-production-data)")
_SITE = "https://www.nnpcgroup.com"
_CDN = "https://fde-nnpc-web-cms-prod-dwfrd0hraahrbhhg.a02.azurefd.net"
_TIMEOUT = 120

_PROVISIONAL = ("NNPC Ltd's own disclosure for NNPC-interest assets. Not "
                "NUPRC data, not a national total. partner_lift_bbl is "
                "DERIVED (crude - equity lift): the published column is "
                "misaligned -- see scripts/scrape_nnpc_disclosures.py.")


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.read()


def _unescape(html: str) -> str:
    return html.replace(chr(92) + "u002F", "/").replace(chr(92) + "/", "/")


def _listing(path: str) -> str:
    return _unescape(_fetch(f"{_SITE}/documents/{path}").decode("utf-8", "replace"))


def _links(html: str) -> list[str]:
    return sorted(set(re.findall(r"/uploads/[A-Za-z0-9._%-]+", html)))


def _folders(html: str, within: str) -> list[str]:
    out = set()
    for m in re.findall(r'"(/documents/[^"]{3,200})"', html):
        if m.startswith(f"/documents/{within}/") and m.count("/") == within.count("/") + 3:
            out.add(m[len("/documents/"):])
    return sorted(out)


def discover(year: int) -> list[dict]:
    """Every quarterly disclosure workbook published for `year`.

    Walks quarter folders and the per-entity folders inside them -- NNPC LTD
    and NNPC E&P LTD publish separately. A handful of listing requests once a
    quarter; nothing is downloaded until a document turns out to be new.
    """
    root = f"{year}%20Documents/{year}%20Quarterly%20Disclosures"
    try:
        html = _listing(root)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            logger.warning("no %s quarterly disclosures folder", year)
            return []
        raise

    out: list[dict] = []
    for quarter in _folders(html, root):
        qhtml = _listing(quarter.replace(" ", "%20"))
        entities = _folders(qhtml, quarter) or [quarter]
        for entity in entities:
            ehtml = qhtml if entity == quarter else _listing(
                entity.replace(" ", "%20").replace("&", "%26"))
            for link in _links(ehtml):
                if not link.lower().endswith((".xlsx", ".xls")):
                    continue
                out.append({
                    "document": link.rsplit("/", 1)[-1],
                    "url": _CDN + link,
                    "quarter": quarter.rsplit("/", 1)[-1],
                    "entity": entity.rsplit("/", 1)[-1],
                })
    return out


def _num(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    return str(value).strip()


def _month(value) -> str:
    """A month key from whatever the cell holds.

    Dates arrive as real datetimes through openpyxl, but the sheets also
    carry month NAMES ("JANUARY") in the production tab, so both are read.
    """
    if isinstance(value, datetime):
        return value.strftime("%Y-%m")
    if isinstance(value, date):
        return value.strftime("%Y-%m")
    return ""


_MONTH_NAMES = {m: i for i, m in enumerate(
    ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY",
     "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"], 1)}


def _headers(ws, limit: int = 4) -> tuple[int, dict[str, int]]:
    """Find the header row and map each column name to its index.

    Read by NAME, never by position. The gas sheet puts its headers on row 2
    under a banner, the lifting sheet on row 1, and the columns are not in
    the same order between the two -- a positional read works on whichever
    sheet it was written against and quietly mis-files the other.
    """
    for row_idx in range(1, limit + 1):
        names = {}
        for cell in ws[row_idx]:
            label = _text(cell.value)
            if label:
                names[re.sub(r"[^a-z0-9]", "", label.lower())] = cell.column - 1
        if len(names) >= 5:
            return row_idx, names
    raise ValueError(f"{ws.title}: no header row in the first {limit} rows")


def _col(names: dict[str, int], *candidates: str) -> int | None:
    for c in candidates:
        key = re.sub(r"[^a-z0-9]", "", c.lower())
        if key in names:
            return names[key]
        for name, idx in names.items():
            if name.startswith(key):
                return idx
    return None


class UnsupportedWorkbook(Exception):
    """Not the multi-company disclosure this script reads.

    NNPC publish several shapes under the same folder and this reads exactly
    one of them: the NNPC LTD / NUIMS workbook whose sheets carry a Company
    column, covering every operator NNPC holds equity with. Deliberately
    skipped, not failed:

    - `NEPL_*` is NNPC E&P Ltd's own assets. One company, so there is no
      Company column and Lifting_Data is a flat cargo list rather than
      totals with a breakdown beneath. It also ships as "Copy of ..." with
      the author's scratch tabs ("Working", "Working (2)") still in it, and
      its Q1 lifting dates read 2026-09-01. Worth adding once someone has
      established what those dates mean; not worth guessing at.
    - `*_Exploration_Disclosure` is licences, wells and discoveries.
    - `*_Commercial_Arrangements_and_Participation` is subsidiaries and
      concessions held.

    Skipping is a report, not silence: main() lists every skipped document.
    """


def parse_workbook(blob: bytes, document: str) -> dict:
    import io

    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(blob), data_only=True, read_only=True)
    # Matched on the EXACT normalised sheet name. NEPL's workbook also holds
    # "Working", "Working (2)" and "Production_Data_Fiscalised", which are
    # the author's intermediate tabs; a fuzzy match would read a scratch
    # sheet as though it were the published one.
    sheets = {re.sub(r"[^a-z]", "", n.lower()): n for n in wb.sheetnames}
    result = {"document": document, "lifting": [], "cargoes": [],
              "production": [], "equity": [], "shift_disagreements": 0,
              "shift_rows": 0}
    try:
        if "liftingdata" not in sheets or "productiondata" not in sheets:
            raise UnsupportedWorkbook(
                f"{document}: sheets are {list(sheets.values())}")
        _parse_lifting(wb[sheets["liftingdata"]], document, result)
        _parse_production(wb[sheets["productiondata"]], document, result)
        if "projectmetadata" in sheets:
            _parse_equity(wb[sheets["projectmetadata"]], document, result)
    finally:
        wb.close()

    if not any((result["lifting"], result["production"])):
        raise UnsupportedWorkbook(f"{document}: no company rows found")
    return result


def _parse_lifting(ws, document: str, result: dict) -> None:
    header_row, names = _headers(ws)
    c_company = _col(names, "company")
    c_field = _col(names, "projectnamefield", "projectname")
    c_date = _col(names, "liftingdate")
    c_crude = _col(names, "crudevolumebbl", "crudevolume")
    c_equity = _col(names, "nnpcequityliftbbl", "nnpcequitylift")
    c_partner = _col(names, "partnerliftbbl", "partnerlift")
    c_cargo = _col(names, "cargoid")
    c_buyer = _col(names, "buyer")
    c_dest = _col(names, "destinationcountry")
    c_mode = _col(names, "exportordomestic")
    if None in (c_company, c_date, c_crude, c_equity):
        # No Company column is the NEPL single-company shape, not damage.
        raise UnsupportedWorkbook(
            f"{document}: lifting sheet has no Company column")

    current: dict | None = None
    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        def at(idx):
            return row[idx] if idx is not None and idx < len(row) else None

        company = _text(at(c_company))
        crude = _num(at(c_crude))
        equity = _num(at(c_equity))
        published_partner = _num(at(c_partner))

        if company:
            # A company header row: its totals for the month, and the parent
            # of the cargo rows that follow it.
            derived = None if (crude is None or equity is None) else crude - equity
            if derived is not None:
                result["shift_rows"] += 1
                # Does NNPC's own cell agree with the arithmetic? Recorded,
                # never trusted -- see the module docstring.
                if published_partner is None or abs(published_partner - derived) > 1:
                    result["shift_disagreements"] += 1
            current = {
                "company": company,
                "field": _text(at(c_field)),
                "month": _month(at(c_date)),
                "crude_volume_bbl": crude,
                "nnpc_equity_lift_bbl": equity,
                "partner_lift_bbl": None if derived is None else round(derived, 2),
                "partner_lift_source_disagreed": (
                    "" if derived is None
                    else int(published_partner is None
                             or abs(published_partner - derived) > 1)),
                "cargoes_listed": 0,
                "cargoes_bbl": 0.0,
                "document": document,
            }
            result["lifting"].append(current)

        cargo_id = _text(at(c_cargo))
        volume = _num(at(c_equity))
        if cargo_id and current is not None and volume:
            # A cargo, carrying NNPC'S EQUITY SHARE of it -- the breakdown
            # rows populate the equity column, not the crude-volume one, and
            # they sum to the company's stated equity lift (which is what
            # _reconcile checks). It is NOT the size of the cargo: Pan Ocean's
            # OML 147 row lifts 161,000 bbl of which NNPC's equity is 1,000.
            # Named in full in the CSV so nobody reads it as the cargo total.
            #
            # On a company header row the cargo columns describe a
            # single-cargo month, so the header's own volume is that cargo.
            result["cargoes"].append({
                "company": current["company"],
                "field": current["field"],
                "month": current["month"],
                "lifting_date": _text(at(c_date)),
                "nnpc_equity_lift_bbl": volume,
                "cargo_id": cargo_id,
                "buyer": _text(at(c_buyer)),
                "destination": _text(at(c_dest)),
                "export_or_domestic": _text(at(c_mode)),
                "document": document,
            })
            current["cargoes_listed"] += 1
            current["cargoes_bbl"] = round(current["cargoes_bbl"] + volume, 2)


def _parse_production(ws, document: str, result: dict) -> None:
    header_row, names = _headers(ws)
    c_company = _col(names, "company")
    c_field = _col(names, "projectnamefield", "projectname")
    c_period = _col(names, "period")
    c_crude = _col(names, "crudeoilproductionbbl", "crudeoilproduction")
    c_cond = _col(names, "condensateproductionbb", "condensateproduction")
    c_gas = _col(names, "gasproductionmmscf", "gasproduction")
    c_lpg = _col(names, "lpgproductiontonnes", "lpgproduction")
    c_boe = _col(names, "totalhydrocarbonboe", "totalhydrocarbon")
    c_daily = _col(names, "averagedailyproduction", "averagedaily")
    if None in (c_company, c_period, c_crude):
        raise UnsupportedWorkbook(
            f"{document}: production sheet has no Company column")

    year = _year_from(document)
    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        def at(idx):
            return row[idx] if idx is not None and idx < len(row) else None

        company = _text(at(c_company))
        if not company:
            continue
        period = _text(at(c_period)).upper()
        month = _month(at(c_period))
        if not month and period in _MONTH_NAMES and year:
            month = f"{year}-{_MONTH_NAMES[period]:02d}"
        result["production"].append({
            "company": company,
            "field": _text(at(c_field)),
            "month": month,
            "crude_oil_bbl": _num(at(c_crude)),
            "condensate_bbl": _num(at(c_cond)),
            "gas_mmscf": _num(at(c_gas)),
            "lpg_tonnes": _num(at(c_lpg)),
            "total_hydrocarbon_boe": _num(at(c_boe)),
            "average_daily_production": _num(at(c_daily)),
            "document": document,
        })


def _parse_equity(ws, document: str, result: dict) -> None:
    header_row, names = _headers(ws)
    c_project = _col(names, "projectname")
    c_blocks = _col(names, "omloplnumber", "omlopl")
    c_contract = _col(names, "contracttype")
    c_operator = _col(names, "operator")
    c_equity = _col(names, "nnpcequity")
    if None in (c_project, c_operator):
        return
    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        def at(idx):
            return row[idx] if idx is not None and idx < len(row) else None

        project = _text(at(c_project))
        if not project:
            continue
        result["equity"].append({
            "project": project,
            "blocks": _text(at(c_blocks)),
            "contract_type": _text(at(c_contract)),
            "operator": _text(at(c_operator)),
            "nnpc_equity_pct": _num(at(c_equity)),
            "document": document,
        })


def _year_from(document: str) -> str:
    m = re.search(r"(20\d\d)", document)
    return m.group(1) if m else ""


def _reconcile(result: dict) -> list[str]:
    """Cargo breakdowns must add up to the company total they sit under.

    NNPC print a company's equity lift for the month and then itemise the
    cargoes that make it up, so the sheet states the same quantity twice.
    Where both are present they must agree -- that is the check that a cargo
    block was attached to the right company.
    """
    problems = []
    for row in result["lifting"]:
        listed, total = row["cargoes_bbl"], row["nnpc_equity_lift_bbl"]
        if row["cargoes_listed"] < 2 or total is None:
            continue
        if abs(listed - total) > max(1.0, abs(total) * 0.001):
            problems.append(
                f"{result['document']}: {row['company']} {row['month']} "
                f"cargoes total {listed:,.0f} against a stated equity lift of "
                f"{total:,.0f}")
    return problems


def _write(path: Path, rows: list[dict], fields: list[str]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(f"# {_PROVISIONAL}\n")
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in sorted(rows, key=lambda r: tuple(
                str(r.get(k) or "") for k in fields[:3])):
            w.writerow(row)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=datetime.now(timezone.utc).year)
    ap.add_argument("--out", default=".")
    ap.add_argument("--file", help="parse a local workbook instead")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    out = Path(args.out)

    if args.file:
        found = [{"document": Path(args.file).name, "url": "",
                  "quarter": "", "entity": ""}]
        blobs = {found[0]["document"]: Path(args.file).read_bytes()}
    else:
        found = discover(args.year)
        blobs = {}
        if not found:
            logger.info("no disclosure workbooks found for %s", args.year)
            return 0

    logger.info("%s workbook(s) listed for %s", len(found), args.year)

    parsed, failures, dead, skipped = [], [], [], []
    for d in found:
        try:
            blob = blobs.get(d["document"]) or _fetch(d["url"])
        except urllib.error.HTTPError as exc:
            # NNPC's CMS lists documents whose blobs are missing: every Q2
            # 2026 file 404s with BlobNotFound while Q1's are fine. That is
            # their publishing fault, not a parse failure, and it must not
            # stop the quarters that ARE readable from being written.
            dead.append(f"{d['document']}: {exc.code} from the CDN")
            continue
        except Exception as exc:
            failures.append(f"{d['document']}: download failed ({exc})")
            continue
        try:
            parsed.append(parse_workbook(blob, d["document"]))
        except UnsupportedWorkbook as exc:
            skipped.append(str(exc))
        except Exception as exc:
            failures.append(str(exc))

    for entry in skipped:
        logger.info("SKIPPED (other document type) %s", entry)
    for entry in dead:
        logger.warning("UNAVAILABLE %s", entry)
    for entry in failures:
        logger.error("REFUSED %s", entry)
    if failures:
        return 1
    if not parsed:
        logger.info("nothing parsed (%s listed but unavailable)", len(dead))
        return 0

    problems = []
    for result in parsed:
        problems.extend(_reconcile(result))
    if problems:
        for p in problems:
            logger.error("REFUSED %s", p)
        return 1

    lifting, cargoes, production, equity = [], [], [], []
    shifted = rows_checked = 0
    for r in parsed:
        lifting += r["lifting"]
        cargoes += r["cargoes"]
        production += r["production"]
        equity += r["equity"]
        shifted += r["shift_disagreements"]
        rows_checked += r["shift_rows"]

    if shifted:
        logger.warning(
            "partner lift: NNPC's own column disagrees with crude minus "
            "equity on %s of %s company rows -- derived values published, "
            "published column ignored", shifted, rows_checked)
    else:
        logger.info("partner lift: NNPC's column agrees on all %s rows "
                    "(still publishing the derived figure)", rows_checked)

    if args.dry_run:
        logger.info("lifting rows %s, cargoes %s, production rows %s, assets %s",
                    len(lifting), len(cargoes), len(production), len(equity))
        for row in cargoes[:5]:
            logger.info("   cargo %s", row)
        return 0

    _write(out / "nnpc_lifting_by_company.csv", lifting,
           ["company", "field", "month", "crude_volume_bbl",
            "nnpc_equity_lift_bbl", "partner_lift_bbl",
            "partner_lift_source_disagreed", "cargoes_listed", "document"])
    _write(out / "nnpc_lifting_cargoes.csv", cargoes,
           ["company", "month", "lifting_date", "field", "nnpc_equity_lift_bbl",
            "cargo_id", "buyer", "destination", "export_or_domestic",
            "document"])
    _write(out / "nnpc_production_by_field.csv", production,
           ["company", "field", "month", "crude_oil_bbl", "condensate_bbl",
            "gas_mmscf", "lpg_tonnes", "total_hydrocarbon_boe",
            "average_daily_production", "document"])
    _write(out / "nnpc_asset_equity.csv", equity,
           ["project", "blocks", "contract_type", "operator",
            "nnpc_equity_pct", "document"])

    with open(out / "nnpc_disclosures_manifest.json", "w", encoding="utf-8") as f:
        # No run date in here. It changed on every run, so the file differed
        # every time even when NNPC had published nothing, and the wrapper
        # committed "disclosures: refresh" monthly to record only that the
        # scraper had run. git log already says when. What belongs in a
        # manifest is which documents were seen, which is what changes when
        # something actually happens.
        json.dump({
            "documents": sorted(r["document"] for r in parsed),
            "unavailable": sorted(dead),
            "skipped_other_document_types": sorted(skipped),
            "partner_lift_rows_where_source_disagreed": shifted,
            "partner_lift_rows_checked": rows_checked,
        }, f, indent=2)
        f.write("\n")

    logger.info("wrote %s lifting rows, %s cargoes, %s production rows, %s assets",
                len(lifting), len(cargoes), len(production), len(equity))
    return 0


if __name__ == "__main__":
    sys.exit(main())
