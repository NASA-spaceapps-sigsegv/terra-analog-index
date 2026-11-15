#!/bin/sh
# Look for secrets before making the repository public (TAI-37).
#
# Checks the tracked files and the whole history (what each commit added, on every branch):
#   - assigned keys: NCBI_API_KEY=..., EARTHDATA_PASSWORD=..., API_KEY / TOKEN / SECRET / PASSWORD
#   - .netrc lines with a user and password
#   - email addresses
#   - files that should never be tracked: .env, .netrc, _netrc, .streamlit/secrets.toml
# Commit authors and Co-Authored-By lines do not count: they are not part of the files.
#
#   sh scripts/check_secrets.sh      (or make check-secrets)
#
# Exits with code 1 if it finds something. A placeholder value (<key>, your_key, tu_clave, xxx, ...)
# does not count as a secret.

cd "$(git rev-parse --show-toplevel)" || exit 2

EMAIL='[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}'
KEY='(NCBI_API_KEY|EARTHDATA_(USERNAME|PASSWORD)|API_KEY|SECRET|TOKEN|PASSWORD)["'"'"']?[[:space:]]*[:=][[:space:]]*["'"'"']?[A-Za-z0-9_./+-]{6,}'
NETRC='machine[[:space:]]+[^[:space:]]+[[:space:]]+login[[:space:]]+[^<[:space:]]+[[:space:]]+password[[:space:]]+[^<[:space:]]+'
PATTERN="$EMAIL|$KEY|$NETRC"
# Placeholders and public addresses that are not secrets (tu_clave: older Spanish placeholder in the history).
ALLOW='noreply@anthropic\.com|@example\.(com|org)|<[^>]*>|tu_clave|your_?key|xxx'
FILES='(^|/)(\.env|\.netrc|_netrc|secrets\.toml)$'

found=0
# $1: title; $2: matches. No pipes into the function: in sh each pipeline runs in a
# subshell and `found` would not get out of it.
report() {
    hits=$(printf '%s\n' "$2" | grep -vE "$ALLOW" | grep -v '^$')
    if [ -n "$hits" ]; then
        printf '\n✗ %s\n%s\n' "$1" "$hits"
        found=1
    fi
}

current=$(git grep -nIE "$PATTERN" -- . ':!scripts/check_secrets.sh')
report "Current files" "$current"

history=$(git log --all -p --format='commit %h' -- . ':!scripts/check_secrets.sh' | awk '
    /^commit / { c = $2; next }
    /^\+\+\+ / { f = substr($0, 7); next }
    /^\+/      { print c " " f ": " substr($0, 2) }
' | grep -E "$PATTERN")
report "History (commit, file: added line)" "$history"

files=$({ git ls-files; git log --all --format= --name-only; } | grep -E "$FILES" | sort -u)
report "Credential files ever tracked" "$files"

if [ "$found" -eq 0 ]; then
    echo "✓ No secrets in the files or in the history."
fi
exit "$found"
