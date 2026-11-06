#!/usr/bin/env bash
# Instala os hooks pre-commit e pre-push que barram segredo (ver hook-segredos.sh).
# Vale para o clone e para todos os worktrees dele. Rode uma vez por clone.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
HOOKS="$(git rev-parse --git-common-dir)/hooks"
mkdir -p "$HOOKS"

instalar() {
  local nome=$1 modo=$2 alvo="$HOOKS/$1"
  if [ -e "$alvo" ] && ! grep -q "hook-segredos.sh" "$alvo"; then
    mv "$alvo" "$alvo.anterior"
    echo "Hook $nome que já existia foi guardado em $alvo.anterior"
  fi
  cat > "$alvo" <<HOOK
#!/usr/bin/env bash
# Instalado por scripts/instalar-hook-de-segredos.sh
"\$(git rev-parse --show-toplevel)/scripts/hook-segredos.sh" $modo || exit 1
if [ -x "$alvo.anterior" ]; then exec "$alvo.anterior" "\$@"; fi
HOOK
  chmod +x "$alvo"
  echo "Instalado: $alvo"
}

instalar pre-commit staged
instalar pre-push push
