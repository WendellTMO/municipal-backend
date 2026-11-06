#!/usr/bin/env bash
# Barra segredo antes de ir para o GitHub (repositório público). Roda as três checagens do
# .pre-commit-config.yaml: arquivo de segredo, credencial colada no código e chave privada.
#
#   scripts/hook-segredos.sh staged   o que está no commit (hook pre-commit)
#   scripts/hook-segredos.sh push     tudo que ainda não está no origin/demo (hook pre-push)
#
# Instalação: scripts/instalar-hook-de-segredos.sh
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

if command -v uv >/dev/null 2>&1; then
  PRECOMMIT=(uv run pre-commit)
else
  PRECOMMIT=(pre-commit)
fi

modo=${1:-staged}
if [ "$modo" = "staged" ]; then
  ARQUIVOS=$(git diff --cached --name-only --diff-filter=ACM)
  if [ -z "$ARQUIVOS" ]; then
    exit 0
  fi
  ESCOPO=(--files $ARQUIVOS)
else
  BASE=$(git merge-base HEAD origin/demo 2>/dev/null || git rev-list --max-parents=0 HEAD | tail -n 1)
  ESCOPO=(--from-ref "$BASE" --to-ref HEAD)
fi

falhou=0
for hook in arquivo-secreto segredo-no-conteudo detect-private-key; do
  if ! "${PRECOMMIT[@]}" run "$hook" "${ESCOPO[@]}" >/tmp/hook-segredos.log 2>&1; then
    cat /tmp/hook-segredos.log
    falhou=1
  fi
done
rm -f /tmp/hook-segredos.log

if [ "$falhou" -ne 0 ]; then
  echo "" >&2
  echo "BLOQUEADO: segredo no que ia para o GitHub. Tire do commit (git reset HEAD arquivo) e deixe fora do git." >&2
  exit 1
fi
