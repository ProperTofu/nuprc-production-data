#!/usr/bin/env bash
# What cron runs. Refreshes one source and pushes if anything changed.
#
#   ./scripts/cron_refresh.sh oil
#   ./scripts/cron_refresh.sh gas
#   ./scripts/cron_refresh.sh rig
#   ./scripts/cron_refresh.sh rigdisp
#   ./scripts/cron_refresh.sh nnpc
#
# A thin entry point on purpose. Putting this in the crontab line itself meant
# a long, quoted one-liner that could not be run by hand to see what it does,
# and cron's environment differs enough from a login shell that testing the
# command you *think* cron runs proves little.
set -uo pipefail

SOURCE="${1:-}"
case "$SOURCE" in
    oil|gas|rig|rigdisp|nnpc) ;;
    *) echo "usage: $0 <oil|gas|rig|rigdisp|nnpc>" >&2; exit 2 ;;
esac

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# cron starts with a near-empty PATH -- typically /usr/bin:/bin -- which is
# enough for docker and git here, but not somewhere to rely on luck.
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# The app's own env file carries the SMTP settings the alert needs. Read
# rather than duplicated, so there is one place to change a password. Absent,
# the scrapers simply log that no alert was sent and still fail loudly.
#
# READ, not sourced. That file is a docker --env-file, in which a value runs
# literally to the end of the line. Bash is not docker, and read the same line
# as code:
#
#   EMAIL_FROM=NUI Terminal <the.nuiterminal@gmail.com>
#
# gave "syntax error near unexpected token `newline'" because bash took the
# angle brackets as redirection. Sourcing stops there, so every variable BELOW
# that line went unset while the script carried on looking healthy. Quoting
# the value in .env would satisfy bash and break docker, which keeps the
# quotes as part of the sender address.
#
# Only the variables the alert needs are taken, split on the first "=" and
# assigned without interpretation, so no value can be executed whatever it
# contains.
ENV_FILE="/home/ubuntu/nui-terminal/.env"
if [ -r "$ENV_FILE" ]; then
    while IFS='=' read -r _key _value; do
        case "$_key" in
            SMTP_HOST|SMTP_PORT|SMTP_USER|SMTP_PASS|EMAIL_FROM)
                export "$_key=$_value" ;;
        esac
    done < "$ENV_FILE"
    unset _key _value
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
    # NUPRC's own register: every rig in country, not just those drilling.
    rigdisp) bash scripts/scrape_rig_disposition.sh --push ;;
    # NNPC Ltd's own monthly summary. Their figures, not NUPRC's: the
    # gas number runs 100-500 mmscf/d below the regulator's every month.
    nnpc) bash scripts/scrape_nnpc_reports.sh --push ;;
esac
status=$?

# Reported rather than swallowed: a non-zero exit here means a guard refused,
# and the scraper has already emailed about it.
if [ $status -ne 0 ]; then
    echo "$(date -Is) $SOURCE FAILED with status $status" >&2
fi
exit $status
