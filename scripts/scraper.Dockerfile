# The image the scrapers run in. Built once, reused by every run.
#
# Previously each run did `pip install` inside a bare python image: ~20MB of
# pymupdf pulled from PyPI on all 33 runs a month, to execute a script that
# takes ten seconds. Mounting pip's cache did not help -- pip refuses a cache
# directory it does not own, and the container runs as root while the host
# directory belongs to the invoking user.
#
# Baking the dependencies in removes the problem rather than working around
# it: no PyPI traffic, no ownership puzzle, and a faster start.
#
# Rebuild after changing these:
#   docker build -f scripts/scraper.Dockerfile -t nui-scraper:latest scripts/
FROM python:3.11-slim

# pymupdf reads the NUPRC production PDFs; openpyxl reads the Baker Hughes
# workbooks. Both scrapers are standard library apart from these.
# pymupdf pinned below 2: on 2.1 page.find_tables() returns no rows for
# either NUPRC PDF, so both oil and gas scrapes fail (checked 2026-11-19
# against the Jan-Oct oil and Jan-Aug gas reports; 1.28.2 reproduces the
# published CSVs exactly). Unpinned, the next image rebuild would break them.
RUN pip install --no-cache-dir "pymupdf==1.28.2" openpyxl
