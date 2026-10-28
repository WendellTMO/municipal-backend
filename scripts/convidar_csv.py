"""Convida alunos em lote a partir de um CSV, usando a API do BusKá.

Uso:
    BUSKA_API_URL=http://localhost:5000 BUSKA_EMAIL=gestor@exemplo.test \\
    BUSKA_SENHA=... uv run python scripts/convidar_csv.py alunos.csv [--dry-run]

Colunas do CSV: nome, email (obrigatórias); telefone, ponto (apelido ou id),
instituicao (nome), rota (nome) (opcionais). A senha vem só do ambiente.
"""

import argparse
import csv
import os
import sys
from typing import Any

import requests

TAMANHO_DO_LOTE = 500
TIMEOUT_SEGUNDOS = 30
COLUNAS_OBRIGATORIAS = ("nome", "email")


def ler_csv(caminho: str) -> list[dict[str, str]]:
    """Lê o CSV e devolve uma linha por aluno, com cabeçalho em minúsculas e valores sem espaços."""
    linhas: list[dict[str, str]] = []
    with open(caminho, newline="", encoding="utf-8-sig") as arquivo:
        leitor = csv.DictReader(arquivo)
        cabecalho: list[str] = []
        for coluna in leitor.fieldnames or []:
            cabecalho.append(coluna.strip().lower())
        for obrigatoria in COLUNAS_OBRIGATORIAS:
            if obrigatoria not in cabecalho:
                raise ValueError(f"Coluna obrigatória ausente no CSV: {obrigatoria}")

        for bruta in leitor:
            linha: dict[str, str] = {}
            for coluna, valor in bruta.items():
                if coluna is None:
                    continue
                linha[coluna.strip().lower()] = (valor or "").strip()
            if not any(linha.values()):
                continue
            linhas.append(linha)
    return linhas


def _achar_id(texto: str, candidatos: list[dict[str, Any]], campo_nome: str) -> str:
    """Id do candidato cujo id ou nome bate com o texto. Levanta ValueError se 0 ou 2+."""
    achados: list[str] = []
    for candidato in candidatos:
        mesmo_id = str(candidato.get("id", "")).lower() == texto.lower()
        mesmo_nome = str(candidato.get(campo_nome) or "").strip().lower() == texto.lower()
        if mesmo_id or mesmo_nome:
            achados.append(str(candidato["id"]))
    if len(achados) == 0:
        raise ValueError(f"não encontrado: {texto}")
    if len(achados) > 1:
        raise ValueError(f"mais de um resultado para: {texto}")
    return achados[0]


def montar_itens(
    linhas: list[dict[str, str]],
    pontos: list[dict[str, Any]],
    instituicoes: list[dict[str, Any]],
    rotas: list[dict[str, Any]],
) -> list[tuple[int, dict[str, str] | None, str]]:
    """Resolve nomes para ids. Devolve (numero_da_linha, payload ou None, erro)."""
    saida: list[tuple[int, dict[str, str] | None, str]] = []
    for posicao, linha in enumerate(linhas, start=2):  # linha 1 do arquivo é o cabeçalho
        item: dict[str, str] = {"nome": linha.get("nome", ""), "email": linha.get("email", "")}
        if linha.get("telefone"):
            item["telefone"] = linha["telefone"]
        try:
            if linha.get("ponto"):
                item["ponto_id"] = _achar_id(linha["ponto"], pontos, "apelido")
            if linha.get("instituicao"):
                item["instituicao_id"] = _achar_id(linha["instituicao"], instituicoes, "nome")
            if linha.get("rota"):
                item["rota_id"] = _achar_id(linha["rota"], rotas, "nome")
        except ValueError as erro:
            saida.append((posicao, None, str(erro)))
            continue
        saida.append((posicao, item, ""))
    return saida


def dividir_em_lotes(itens: list[Any], tamanho: int = TAMANHO_DO_LOTE) -> list[list[Any]]:
    lotes: list[list[Any]] = []
    for inicio in range(0, len(itens), tamanho):
        lotes.append(itens[inicio : inicio + tamanho])
    return lotes


def fazer_login(base: str, email: str, senha: str) -> dict[str, str]:
    resposta = requests.post(
        f"{base}/v1/auth/login",
        json={"email": email, "password": senha},
        timeout=TIMEOUT_SEGUNDOS,
    )
    resposta.raise_for_status()
    dados = resposta.json()
    token = dados.get("token") or dados.get("access_token")
    if not token:
        raise RuntimeError("Login sem token na resposta")
    return {"Authorization": f"Bearer {token}"}


def listar(base: str, cabecalhos: dict[str, str], caminho: str) -> list[dict[str, Any]]:
    resposta = requests.get(f"{base}{caminho}", headers=cabecalhos, timeout=TIMEOUT_SEGUNDOS)
    resposta.raise_for_status()
    return resposta.json().get("items", [])


def enviar_lote(base: str, cabecalhos: dict[str, str], lote: list[dict[str, str]]) -> list[Any]:
    resposta = requests.post(
        f"{base}/v1/convites/",
        json={"convites": lote},
        headers=cabecalhos,
        timeout=TIMEOUT_SEGUNDOS,
    )
    resposta.raise_for_status()
    return resposta.json()["items"]


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(description="Convida alunos em lote a partir de um CSV")
    analisador.add_argument("csv", help="caminho do arquivo CSV")
    analisador.add_argument("--dry-run", action="store_true", help="valida sem criar convites")
    args = analisador.parse_args(argv)

    base = os.environ.get("BUSKA_API_URL", "").rstrip("/")
    email = os.environ.get("BUSKA_EMAIL", "")
    senha = os.environ.get("BUSKA_SENHA", "")
    if not base or not email or not senha:
        print("Defina BUSKA_API_URL, BUSKA_EMAIL e BUSKA_SENHA no ambiente.", file=sys.stderr)
        return 2

    linhas = ler_csv(args.csv)
    cabecalhos = fazer_login(base, email, senha)
    pontos = listar(base, cabecalhos, "/v1/pontos/")
    instituicoes = listar(base, cabecalhos, "/v1/instituicoes/")
    rotas = listar(base, cabecalhos, "/v1/rotas/")

    problemas = 0
    validos: list[dict[str, str]] = []
    for numero, item, erro in montar_itens(linhas, pontos, instituicoes, rotas):
        if item is None:
            problemas += 1
            print(f"linha {numero}: INVALIDO ({erro})")
        else:
            validos.append(item)

    if args.dry_run:
        for item in validos:
            print(f"dry-run: convidaria {item['email']} ({item})")
        print(f"dry-run: {len(validos)} convite(s) válidos, {problemas} com problema.")
        return 1 if problemas else 0

    for lote in dividir_em_lotes(validos):
        for linha in enviar_lote(base, cabecalhos, lote):
            print(f"{linha['email']}: {linha['resultado']} {linha['motivo']}".rstrip())
            if linha["resultado"] == "INVALIDO":
                problemas += 1
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
