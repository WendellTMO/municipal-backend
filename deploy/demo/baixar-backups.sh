#!/usr/bin/env bash
# Copia para este computador o backup mais recente do banco e a chave do APK, que ficam só na VM.
# Rode de vez em quando (por exemplo toda semana). Os arquivos têm dados pessoais e a chave de assinatura:
# ficam em ~/buska-backups com acesso só do seu usuário. Não suba para o GitHub nem para a nuvem.
#
#   deploy/demo/baixar-backups.sh
set -euo pipefail

VM=${VM:-ubuntu@buska.lsd.ufcg.edu.br}
DEST=${DEST:-$HOME/buska-backups}
umask 077
mkdir -p "$DEST/banco" "$DEST/chave-apk"
chmod 700 "$DEST" "$DEST/banco" "$DEST/chave-apk"

ULTIMO=$(ssh "$VM" 'ls -1t ~/backups/diario-*.dump 2>/dev/null | head -1')
if [ -z "$ULTIMO" ]; then
  echo "Nenhum backup diário na VM ainda." >&2
  exit 1
fi
rsync -t "$VM:$ULTIMO" "$DEST/banco/"
rsync -t "$VM:~/buska-demo-release.keystore" "$VM:~/buska-demo-keystore.pass" "$DEST/chave-apk/"

# Guarda só os 5 dumps mais recentes aqui.
ls -1t "$DEST"/banco/diario-*.dump | tail -n +6 | xargs -I{} rm -f {}
echo "Copiado para $DEST:"
ls -la "$DEST/banco" "$DEST/chave-apk" | awk '{print $5, $9}' | grep -v '^ *$'
