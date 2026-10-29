#!/usr/bin/env bash
# Gera (e opcionalmente publica) o APK da demo. Rodar na VM, como o usuário do runner.
# Variáveis: BRANCH, API_URL, MIN_VERSION_CODE, NOTAS (separadas por |), PUBLICAR (0 ou 1).
set -euo pipefail
set +x

BRANCH=${BRANCH:-demo}
API_URL=${API_URL:-https://buska.lsd.ufcg.edu.br}
MIN_VERSION_CODE=${MIN_VERSION_CODE:-0}
PUBLICAR=${PUBLICAR:-0}
NOTAS=${NOTAS:-}

QUI=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
T=~/actions-runner-front/_work/_tool
export JAVA_HOME=$T/Java_Zulu_jdk/17.0.18-8/x64
export PATH=$JAVA_HOME/bin:$T/node/18.20.8/x64/bin:$PATH
export ANDROID_SDK_ROOT=~/.android/sdk
KS=~/buska-demo-release.keystore
PASS_FILE=~/buska-demo-keystore.pass
WWW=/var/www/buska-app

# Keystore: criado uma única vez. Trocar a chave impede atualizar por cima do app instalado.
if [ ! -f "$KS" ]; then
    umask 077
    openssl rand -hex 16 > "$PASS_FILE"
    keytool -genkeypair -keystore "$KS" -storepass:file "$PASS_FILE" -keypass:file "$PASS_FILE" \
        -alias buska-demo -keyalg RSA -keysize 2048 -validity 3650 -dname "CN=BusKa Demo"
fi
chmod 600 "$PASS_FILE" "$KS"
SENHA=$(cat "$PASS_FILE")

rm -rf ~/buska-front-demo
git clone -q -b "$BRANCH" https://github.com/WendellTMO/municipal-frontend.git ~/buska-front-demo
cd ~/buska-front-demo

# Sem NOTAS, usa os assuntos dos últimos commits.
# shortcut: não sabe qual commit foi publicado antes, pega os 5 últimos; guardar o hash no JSON se precisar.
if [ -z "$NOTAS" ]; then
    NOTAS=$(git log -5 --format=%s | paste -sd '|' -)
fi
if [ -z "$NOTAS" ]; then
    NOTAS="Melhorias e correções"
fi

VERSION_NAME=$(node -p "require('./package.json').version")
export BUSKA_VERSION_CODE=$(( $(date +%s) / 60 ))

printf "API_URL=%s\nAPP_NAME=BusKá\n" "$API_URL" > .env
npm ci
echo "sdk.dir=$ANDROID_SDK_ROOT" > android/local.properties
cp "$KS" android/app/buska-release-key.keystore
cat > android/keystore.properties <<PROPS
debug.storeFile=debug.keystore
debug.storePassword=android
debug.keyAlias=androiddebugkey
debug.keyPassword=android
release.storeFile=buska-release-key.keystore
release.storePassword=$SENHA
release.keyAlias=buska-demo
release.keyPassword=$SENHA
PROPS
chmod 600 android/keystore.properties

cd android && chmod +x gradlew
./gradlew assembleRelease --no-daemon --max-workers=2 -Dorg.gradle.caching=false \
    -Dorg.gradle.jvmargs="-Xmx2g -XX:MaxMetaspaceSize=512m"
cp app/build/outputs/apk/release/*.apk ~/buska-demo.apk
APK=~/buska-demo.apk

[ -f "$APK" ] || { echo "APK não encontrado: $APK" >&2; exit 1; }
APKSIGNER=$(ls ~/.android/sdk/build-tools/*/apksigner | sort -V | tail -1)
"$APKSIGNER" verify "$APK" || { echo "Assinatura do APK inválida, abortando." >&2; exit 1; }
echo "Certificado do assinante:"
"$APKSIGNER" verify --print-certs "$APK" | grep "SHA-256 digest" | head -1

echo "APK gerado: $APK (versionCode $BUSKA_VERSION_CODE, versionName $VERSION_NAME-beta)"

if [ "$PUBLICAR" = "1" ]; then
    if [ -f "$WWW/app-version.json" ]; then
        ATUAL=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["versionCode"])' \
            "$WWW/app-version.json")
        if [ "$BUSKA_VERSION_CODE" -le "$ATUAL" ]; then
            echo "versionCode $BUSKA_VERSION_CODE não é maior que o publicado ($ATUAL), abortando." >&2
            exit 1
        fi
    fi

    SHA=$(sha256sum "$APK" | cut -d' ' -f1)
    JSON=$(mktemp)
    python3 "$QUI/gerar_app_version.py" --version-code "$BUSKA_VERSION_CODE" \
        --version-name "$VERSION_NAME-beta" --api-url "$API_URL" --sha256 "$SHA" \
        --notas "$NOTAS" --min-version-code "$MIN_VERSION_CODE" > "$JSON"

    # Ordem: anterior, novo APK, e o JSON por último, para nunca apontar para APK ausente.
    if [ -f "$WWW/buska.apk" ]; then
        sudo cp "$WWW/buska.apk" "$WWW/buska-anterior.apk"
    fi
    sudo cp "$APK" "$WWW/.buska.apk.tmp"
    sudo mv "$WWW/.buska.apk.tmp" "$WWW/buska.apk"
    sudo cp "$JSON" "$WWW/.app-version.json.tmp"
    sudo chmod 644 "$WWW/.app-version.json.tmp" "$WWW/buska.apk"
    sudo mv "$WWW/.app-version.json.tmp" "$WWW/app-version.json"
    rm -f "$JSON"
    echo "Publicado em $WWW."
fi

echo "Lembrete: faça backup de ~/buska-demo-release.keystore e ~/buska-demo-keystore.pass (sem a chave ninguém atualiza por cima)."
