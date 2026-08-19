#!/usr/bin/env bash
# Rebuild a year's oil_YYYY.csv from NUPRC's published PDF and commit it.
#
#   ./scripts/scrape_nuprc.sh 2026 ~/JAN_TO_JULY_BOPD_xxx.pdf
#   ./scripts/scrape_nuprc.sh 2026 ~/2026-Monthly-Gas-Data_June.pdf --kind gas
#   ./scripts/scrape_nuprc.sh 2026 <pdf> --dry-run
#
# The report is cumulative: the July release carries January through July, so
# the newest one supersedes every earlier month, revisions included. Always
# pass the latest, and let the script rewrite the whole year.
#
# pymupdf reads the PDF and is installed into a throwaway container rather
# than onto the host, since this runs once a month. Nothing else is needed:
# the script itself is standard library only.
set -euo pipefail

if [ $# -lt 2 ]; then
    echo "usage: $0 <year> <pdf-url-or-path> [--kind gas] [--dry-run]" >&2
    echo "                                     [--allow-new-terminals] [--allow-fewer-months]" >&2
    exit 1
fi

YEAR="$1"; SOURCE="$2"; shift 2
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# A local PDF has to be visible from inside the container, so it is mounted
# alongside the repo rather than assumed to be reachable by the same path.
MOUNT=()
ARG="$SOURCE"
if [ -f "$SOURCE" ]; then
    MOUNT=(-v "$(cd "$(dirname "$SOURCE")" && pwd)/$(basename "$SOURCE"):/input.pdf:ro")
    ARG="/input.pdf"
fi

docker run --rm \
    -v "$REPO:/work" -w /work "${MOUNT[@]}" \
    python:3.11-slim \
    bash -c "pip install --quiet pymupdf && python scripts/scrape_nuprc.py \
        --url \"$ARG\" --year \"$YEAR\" --out /work $*"

# --dry-run writes nothing, so there is nothing to commit and git would fail
# the whole script on an empty commit.
if [[ " $* " == *" --dry-run "* ]]; then
    exit 0
fi

cd "$REPO"
# Which CSV was rebuilt, so the right file is staged. The kind arrives as
# "--kind gas" among the passthrough arguments.
KIND="oil"
[[ " $* " == *" gas "* ]] && KIND="gas"
if git diff --quiet -- "${KIND}_${YEAR}.csv"; then
    echo "${KIND}_${YEAR}.csv unchanged, nothing to commit"
    exit 0
fi

git add "${KIND}_${YEAR}.csv"
git commit -m "${YEAR}: rebuild ${KIND} from the NUPRC report"
echo
echo "Committed. Review with 'git show', then: git push"
