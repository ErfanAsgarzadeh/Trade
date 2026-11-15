#!/usr/bin/env bash
# Monthly restore test: restore the NEWEST dump from runtime/backups into a throwaway database on the db service and print the
# row counts of users and license_orders. The real database is never touched; the throwaway database is dropped at the end.
#
#   tools/portal_backup_check.sh [compose-file] [backup-directory]
#
# By default the database tools run inside the `db` service (docker compose exec). PORTAL_BACKUP_CHECK_RUN can replace that
# prefix, e.g. PORTAL_BACKUP_CHECK_RUN=env to use psql/createdb/dropdb from the local machine (PGHOST, PGUSER, PGPASSWORD, ...).
set -euo pipefail

compose_file="${1:-portal-postgres-compose.yml}"
directory="${2:-runtime/backups}"
database_user="${PORTAL_BACKUP_CHECK_USER:-trade_portal}"

newest="$(ls -1t "$directory"/portal-*.sql.gz 2>/dev/null | head -n 1 || true)"
if [ -z "$newest" ]; then
  echo "No dump found in $directory (expected portal-*.sql.gz)." >&2
  exit 1
fi
if ! gzip -t "$newest"; then
  echo "The newest dump is not a valid gzip file: $newest" >&2
  exit 1
fi

if [ -n "${PORTAL_BACKUP_CHECK_RUN:-}" ]; then
  run=($PORTAL_BACKUP_CHECK_RUN)
else
  run=(docker compose -f "$compose_file" exec -T db)
fi

scratch="portal_restore_check_$(date +%s)_$$"
cleanup() { "${run[@]}" dropdb --if-exists -U "$database_user" "$scratch" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "Restoring $newest into throwaway database $scratch ..."
"${run[@]}" createdb -U "$database_user" "$scratch"
gunzip -c "$newest" | "${run[@]}" psql -v ON_ERROR_STOP=1 -q -U "$database_user" -d "$scratch" >/dev/null
echo "Row counts in the restored copy:"
"${run[@]}" psql -U "$database_user" -d "$scratch" -tA -F ' ' \
  -c "SELECT 'users', COUNT(*) FROM users UNION ALL SELECT 'license_orders', COUNT(*) FROM license_orders"
echo "Restore check finished; the throwaway database is being dropped."
