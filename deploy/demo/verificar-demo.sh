#!/usr/bin/env bash
# Confere o que está no ar na demo. Sai com erro se qualquer verificação falhar.
# Roda no fim de publicar-web-demo.sh e de build-apk-demo.sh, e pode ser rodado à mão.
# Só usa curl. Variáveis: URL, LOGIN_EMAIL, LOGIN_SENHA, CURL_RESOLVE (host:porta:ip, para rodar
# na própria VM, que não resolve o domínio público).
set -uo pipefail

URL=${URL:-https://buska.lsd.ufcg.edu.br}
LOGIN_EMAIL=${LOGIN_EMAIL:-aluno@buska.app}
LOGIN_SENHA=${LOGIN_SENHA:-buska123}
FALHAS=0

curl() { command curl ${CURL_RESOLVE:+--resolve "$CURL_RESOLVE"} "$@"; }

ok() { echo "  ok    $1"; }
falha() { echo "  FALHA $1"; FALHAS=$((FALHAS + 1)); }

codigo() { curl -s -o /dev/null -w "%{http_code}" "$@"; }

echo "Verificando $URL"

# Páginas e API respondem
for caminho in / /landing-page/ /v1/cep/58429900 /app-version.json; do
    c=$(codigo "$URL$caminho")
    if [ "$c" = "200" ]; then ok "$caminho responde 200"; else falha "$caminho respondeu $c"; fi
done

# O site chama a API certa. Já foi ao ar chamando localhost por causa do .env do desenvolvedor.
BUNDLE=$(curl -s "$URL/bundle.js")
if echo "$BUNDLE" | grep -q "$URL"; then ok "bundle.js contém $URL"; else falha "bundle.js não contém $URL"; fi
if echo "$BUNDLE" | grep -qE "localhost:(3000|3001)"; then falha "bundle.js aponta para localhost"; else ok "bundle.js sem localhost de desenvolvimento"; fi

# Login: conta certa entra, senha errada é recusada com 401 (não some como erro de rede)
corpo=$(curl -s -X POST "$URL/v1/auth/login" -H 'Content-Type: application/json' \
    -d "{\"email\":\"$LOGIN_EMAIL\",\"password\":\"$LOGIN_SENHA\"}")
if echo "$corpo" | grep -q '"token"'; then ok "login de $LOGIN_EMAIL devolve token"; else falha "login de $LOGIN_EMAIL não devolveu token"; fi
c=$(codigo -X POST "$URL/v1/auth/login" -H 'Content-Type: application/json' \
    -d "{\"email\":\"$LOGIN_EMAIL\",\"password\":\"senha-errada-123\"}")
if [ "$c" = "401" ]; then ok "senha errada responde 401"; else falha "senha errada respondeu $c"; fi

# Compressão e cache
if curl -sI -H 'Accept-Encoding: gzip' "$URL/bundle.js" | grep -qi "content-encoding: gzip"; then ok "bundle.js vem comprimido"; else falha "bundle.js sem gzip"; fi
if curl -sI "$URL/app-version.json" | grep -qi "cache-control:.*no-cache"; then ok "app-version.json sem cache"; else falha "app-version.json com cache"; fi

# APK: o hash do arquivo servido bate com o app-version.json
JSON=$(curl -s "$URL/app-version.json")
esperado=$(echo "$JSON" | sed -n 's/.*"sha256": *"\([0-9a-f]*\)".*/\1/p')
servido=$(curl -s "$URL/buska.apk" | shasum -a 256 | cut -d' ' -f1)
if [ -n "$esperado" ] && [ "$esperado" = "$servido" ]; then ok "hash do APK bate com app-version.json"; else falha "hash do APK difere do app-version.json"; fi
versao=$(echo "$JSON" | sed -n 's/.*"versionCode": *\([0-9]*\).*/\1/p')
if [ -n "$versao" ] && [ "$versao" -gt 1 ]; then ok "versionCode $versao"; else falha "versionCode inválido ($versao)"; fi

if [ "$FALHAS" -gt 0 ]; then
    echo "$FALHAS verificação(ões) falharam."
    exit 1
fi
echo "Tudo certo."
