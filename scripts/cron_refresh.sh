#!/usr/bin/env bash
# What cron runs. Refreshes one source and pushes if anything changed.
#
#   ./scripts/cron_refresh.sh oil
#   ./scripts/cron_refresh.sh gas
#   ./scripts/cron_refresh.sh rig
#
# A thin entry point on purpose. Putting this in the crontab line itself meant
# a long, quoted one-liner that could not be run by hand to see what it does,
# and cron's environment differs enough from a login shell that testing the
# command you *think* cron runs proves little.
set -uo pipefail

SOURCE="${1:-}"
case "$SOURCE" in
    oil|gas|rig) ;;
    *) echo "usage: $0 <oil|gas|rig>" >&2; exit 2 ;;
esac

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# cron starts with a near-empty PATH -- typically /usr/bin:/bin -- which is
# enough for docker and git here, but not somewhere to rely on luck.
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# The app's own env file carries the SMTP settings the alert needs. Sourced
# rather than duplicated, so there is one place to change a password. Absent,
# the scrapers simply log that no alert was sent and still fail loudly.
ENV_FILE="/home/ubuntu/nui-terminal/.env"
if [ -r "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
fi
# Alerts go to a person, not to the terminal's own mailbox.
export ALERT_EMAIL="${ALERT_EMAIL:-vallychivia@gmail.com}"

cd "$REPO"

# Pull first: the checkout must not fall behind, or a push later is rejected
# and the run looks like a data problem when it is a stale clone.
git pull --ff-only --quiet || {
    echo "$(date -Is) pull failed, skipping run" >&2
    exit 1
}

echo "=== $(date -Is) refreshing $SOURCE"
case "$SOURCE" in
    oil) bash scripts/scrape_nuprc.sh --push ;;
    gas) bash scripts/scrape_nuprc.sh --kind gas --push ;;
    rig) bash scripts/scrape_rig_count.sh --push ;;
esac
status=$?

# Reported rather than swallowed: a non-zero exit here means a guard refused,
# and the scraper has already emailed about it.
if [ $status -ne 0 ]; then
    echo "$(date -Is) $SOURCE FAILED with status $status" >&2
fi
exit $status
