#!/usr/bin/env bash
# Relatório da telemetria de uso do app, direto do banco de produção. Rode na VM:
#
#   deploy/demo/relatorio-telemetria.sh        # últimos 7 dias
#   deploy/demo/relatorio-telemetria.sh 30     # últimos 30 dias
#
# Só lê. Os eventos não têm nome, e-mail, CPF nem localização; usuário aparece como contagem.
set -euo pipefail
DIAS=${1:-7}
CONTAINER=${CONTAINER:-buska_db_prod}
case "$DIAS" in (*[!0-9]*|"") echo "Uso: $0 [dias]" >&2; exit 1;; esac
docker exec -i "$CONTAINER" sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -v dias=$DIAS -P pager=off" < "$(dirname "${BASH_SOURCE[0]}")/relatorio-telemetria.sql"
