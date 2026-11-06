#!/usr/bin/env bash
# Backup diário do banco da demo, rodado pelo cron da VM às 03:00.
# Grava ~/backups/diario-AAAAMMDD-HHMM.dump, confere que o arquivo abre e guarda os 7 mais recentes.
# Também mantém só os 10 dumps mais recentes de antes de deploy.
#
#   deploy/demo/backup-diario.sh                (MANTER=7 DEST=~/backups por padrão)
set -euo pipefail

DEST=${DEST:-$HOME/backups}
MANTER=${MANTER:-7}
mkdir -p "$DEST"

LIVRE_MB=$(df -Pm "$DEST" | awk 'NR==2 {print $4}')
if [ "$LIVRE_MB" -lt 1000 ]; then
  echo "$(date -Is) ERRO: só $LIVRE_MB MB livres em $DEST, backup não feito" >&2
  exit 1
fi

ARQ="$DEST/diario-$(date +%Y%m%d-%H%M).dump"
trap 'rm -f "$ARQ.parcial"' EXIT
docker exec buska_db_prod sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$ARQ.parcial"
# pg_restore --list lê o índice do arquivo e falha se o dump veio cortado.
docker exec -i buska_db_prod pg_restore --list < "$ARQ.parcial" > /dev/null
mv "$ARQ.parcial" "$ARQ"
echo "$(date -Is) ok $ARQ $(du -h "$ARQ" | cut -f1)"

ls -1t "$DEST"/diario-*.dump | tail -n +$((MANTER + 1)) | xargs -r rm -f
ls -1t "$DEST"/antes-deploy-*.dump 2>/dev/null | tail -n +11 | xargs -r rm -f
