"""Gera o app-version.json que o app consulta para saber se há versão nova."""

import argparse
import json
from datetime import UTC, datetime
from urllib.parse import urlsplit


def montar_manifesto(
    version_code: int,
    version_name: str,
    api_url: str,
    sha256: str,
    notas: str,
    min_version_code: int,
    agora: datetime | None = None,
) -> dict:
    partes = urlsplit(api_url)
    apk_url = f"{partes.scheme}://{partes.netloc}/buska.apk"

    lista_notas: list[str] = []
    for nota in notas.split("|"):
        nota = nota.strip()
        if nota:
            lista_notas.append(nota)

    if agora is None:
        agora = datetime.now(UTC)

    return {
        "versionCode": version_code,
        "versionName": version_name,
        "apkUrl": apk_url,
        "sha256": sha256,
        "notas": lista_notas,
        "minVersionCode": min_version_code,
        "publicadoEm": agora.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--version-code", type=int, required=True)
    p.add_argument("--version-name", required=True)
    p.add_argument("--api-url", required=True)
    p.add_argument("--sha256", required=True)
    p.add_argument("--notas", required=True)
    p.add_argument("--min-version-code", type=int, default=0)
    args = p.parse_args()

    manifesto = montar_manifesto(
        args.version_code,
        args.version_name,
        args.api_url,
        args.sha256,
        args.notas,
        args.min_version_code,
    )
    print(json.dumps(manifesto, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
