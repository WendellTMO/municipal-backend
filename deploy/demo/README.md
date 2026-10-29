# Deploy da demo

## Gerar e publicar o APK

Na VM, como o usuário do runner do front:

```bash
deploy/demo/build-apk-demo.sh                 # só gera ~/buska-demo.apk
PUBLICAR=1 NOTAS="Mapa mais rápido|Correção no login" deploy/demo/build-apk-demo.sh
```

No seu computador (o site web), sem usar o `.env` do seu clone:

```bash
deploy/demo/publicar-web-demo.sh
```

`deploy/demo/verificar-demo.sh` confere o que está no ar (páginas, API, login, bundle sem localhost, hash do APK) e sai com erro se algo falhar. Os dois scripts acima já o rodam no fim.

## Simular o ônibus (para mostrar a demo)

Cria o horário de agora e a viagem de hoje, inicia como motorista e move o ônibus pelas ruas
entre os pontos da rota. Quem estiver confirmado na rota vê o ônibus na tela de localização.

```bash
python3 deploy/demo/simular-viagem.py                      # 5 minutos, viagem segue em andamento
python3 deploy/demo/simular-viagem.py --duracao 600 --finalizar
```

Opções: `--rota`, `--sentido`, `--duracao`, `--passo`, `--url`, `--gestor`, `--motorista`, `--senha`.
Se já houver uma viagem em andamento na rota, ela é reaproveitada.

Variáveis (todas opcionais):

| Variável | Padrão |
|---|---|
| `BRANCH` | `demo` |
| `API_URL` | `https://buska.lsd.ufcg.edu.br` |
| `MIN_VERSION_CODE` | `0` |
| `NOTAS` | assuntos dos 5 últimos commits do front, ou "Melhorias e correções" |
| `PUBLICAR` | `0` |

O versionCode é `minutos desde 1970` e chega ao gradle em `BUSKA_VERSION_CODE`.
O versionName vem do `version` do `package.json` do front, sem alteração (ele já inclui o sufixo, por exemplo `1.0.4-beta`).
Com `PUBLICAR=1` o script aborta se a assinatura não passar no `apksigner` ou se o
versionCode não for maior que o de `app-version.json` já publicado.

A publicação em `/var/www/buska-app` segue esta ordem: `buska-anterior.apk`,
`buska.apk` e por último `app-version.json` (escrita atômica via `mv`).

Faça backup de `~/buska-demo-release.keystore` e `~/buska-demo-keystore.pass`.
Sem a mesma chave ninguém consegue atualizar o app por cima.

## app-version.json

```json
{
  "versionCode": 29000000,
  "versionName": "1.2.0-beta",
  "apkUrl": "https://buska.lsd.ufcg.edu.br/buska.apk",
  "sha256": "<hash do apk>",
  "notas": ["Mapa mais rápido", "Correção no login"],
  "minVersionCode": 0,
  "publicadoEm": "2026-10-28T12:00:05Z"
}
```

`minVersionCode` força a atualização: apps instalados com versionCode menor que ele
devem bloquear o uso até atualizar. Com `0` a atualização é opcional.

## nginx

`nginx-demo.conf` serve `/app-version.json` com `Cache-Control: no-cache`, antes do
`location /`, para o app sempre ver a versão publicada mais recente.
