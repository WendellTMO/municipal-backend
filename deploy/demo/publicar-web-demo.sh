#!/usr/bin/env bash
# Gera o app web da demo numa cópia limpa da branch demo do front e publica na VM.
# Rodar no computador de desenvolvimento. Não usa o .env do seu clone: ele costuma ter
# API_URL de desenvolvimento, e esse endereço ia parar dentro do site.
# Variáveis: FRONT_REPO (clone do front), VM, API_URL.
set -euo pipefail

FRONT_REPO=${FRONT_REPO:-$HOME/Documents/buska-frontend}
VM=${VM:-ubuntu@buska.lsd.ufcg.edu.br}
API_URL=${API_URL:-https://buska.lsd.ufcg.edu.br}
COPIA=$(mktemp -d)/front
trap 'git -C "$FRONT_REPO" worktree remove --force "$COPIA" 2>/dev/null || true' EXIT

git -C "$FRONT_REPO" fetch -q fork
git -C "$FRONT_REPO" worktree add -q --detach "$COPIA" fork/demo
ln -s "$FRONT_REPO/node_modules" "$COPIA/node_modules"

(cd "$COPIA" && API_URL="$API_URL" NODE_ENV=production npx webpack --mode production)

# Trava: o site nunca sobe com o endereço de outra API (por exemplo, o de quem gerou).
if ! grep -q "$API_URL" "$COPIA/dist/bundle.js"; then
    echo "ERRO: o bundle não contém $API_URL. Nada foi publicado." >&2
    exit 1
fi

# Copia sem apagar buska.apk, buska-anterior.apk, app-version.json nem a landing page.
rsync -rt "$COPIA/dist/" "$VM:~/web-new/"
ssh "$VM" 'sudo rsync -rt --no-owner --no-group ~/web-new/ /var/www/buska-app/'
echo "Web publicado em $API_URL"
URL="$API_URL" "$(dirname "${BASH_SOURCE[0]}")/verificar-demo.sh"
