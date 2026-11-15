#!/bin/sh
# Busca secretos antes de hacer público el repositorio (TAI-37).
#
# Revisa los archivos versionados y todo el historial (lo que agregó cada commit, en todas las ramas):
#   - claves asignadas: NCBI_API_KEY=..., EARTHDATA_PASSWORD=..., API_KEY / TOKEN / SECRET / PASSWORD
#   - líneas de .netrc con usuario y contraseña
#   - direcciones de correo
#   - archivos que nunca deberían versionarse: .env, .netrc, _netrc, .streamlit/secrets.toml
# Los autores de los commits y las líneas Co-Authored-By no cuentan: no son parte de los archivos.
#
#   sh scripts/check_secrets.sh      (o make check-secrets)
#
# Sale con código 1 si encuentra algo. Un valor de ejemplo (<clave>, tu_clave, your_key, xxx, ...)
# no cuenta como secreto.

cd "$(git rev-parse --show-toplevel)" || exit 2

EMAIL='[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}'
KEY='(NCBI_API_KEY|EARTHDATA_(USERNAME|PASSWORD)|API_KEY|SECRET|TOKEN|PASSWORD)["'"'"']?[[:space:]]*[:=][[:space:]]*["'"'"']?[A-Za-z0-9_./+-]{6,}'
NETRC='machine[[:space:]]+[^[:space:]]+[[:space:]]+login[[:space:]]+[^<[:space:]]+[[:space:]]+password[[:space:]]+[^<[:space:]]+'
PATTERN="$EMAIL|$KEY|$NETRC"
# Ejemplos y direcciones públicas que no son secretos.
ALLOW='noreply@anthropic\.com|@example\.(com|org)|<[^>]*>|tu_clave|your_?key|xxx'
FILES='(^|/)(\.env|\.netrc|_netrc|secrets\.toml)$'

found=0
# $1: título; $2: coincidencias. Sin tuberías hacia la función: en sh cada tubería corre en un
# subshell y `found` no saldría de ahí.
report() {
    hits=$(printf '%s\n' "$2" | grep -vE "$ALLOW" | grep -v '^$')
    if [ -n "$hits" ]; then
        printf '\n✗ %s\n%s\n' "$1" "$hits"
        found=1
    fi
}

current=$(git grep -nIE "$PATTERN" -- . ':!scripts/check_secrets.sh')
report "Archivos actuales" "$current"

history=$(git log --all -p --format='commit %h' -- . ':!scripts/check_secrets.sh' | awk '
    /^commit / { c = $2; next }
    /^\+\+\+ / { f = substr($0, 7); next }
    /^\+/      { print c " " f ": " substr($0, 2) }
' | grep -E "$PATTERN")
report "Historial (commit, archivo: línea agregada)" "$history"

files=$({ git ls-files; git log --all --format= --name-only; } | grep -E "$FILES" | sort -u)
report "Archivos de credenciales versionados alguna vez" "$files"

if [ "$found" -eq 0 ]; then
    echo "✓ Sin secretos en los archivos ni en el historial."
fi
exit "$found"
