#!/bin/bash
set -euo pipefail

# database name is configurable per-run; keep second_brain as the safe default
db="${BACKUP_DATABASE:-second_brain}"
dest="/backups/${db}_$(date +%Y%m%d_%H%M%S).sql.gz"

echo "[backup] $(date -Iseconds) starting pg_dump of database '${db}' -> ${dest}"
pg_dump -h "${PGHOST:-postgres}" -p "${PGPORT:-5432}" -U "${PGUSER:-second_brain}" \
  -F p -d "${db}" | gzip > "${dest}"
echo "[backup] $(date -Iseconds) finished pg_dump of database '${db}'"
