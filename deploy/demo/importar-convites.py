#!/usr/bin/env python3
"""Cria os convites dos alunos a partir das respostas do formulário (CSV exportado do Google Sheets).

Por padrão só SIMULA: lê o CSV, confere cada linha, procura a instituição no BusKá e grava um
relatório, sem criar nada nem mandar e-mail. Com --enviar cria os convites (o BusKá manda o e-mail
com o link e o PIN, no máximo 1 minuto depois).

    export BUSKA_GESTOR_EMAIL=...   BUSKA_GESTOR_SENHA=...
    python3 deploy/demo/importar-convites.py respostas.csv             # simulação
    python3 deploy/demo/importar-convites.py respostas.csv --enviar    # cria os convites

O CSV traz dados pessoais dos alunos. Guarde fora do repositório (por exemplo em ~/buska-backups) e
apague depois da importação. O .gitignore barra *respostas*.csv e *-relatorio-*.csv por segurança.
"""
import argparse
import csv
import datetime
import difflib
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request

TAMANHO_DO_LOTE = 100
CORTE_CERTO = 0.92
CORTE_PROVAVEL = 0.80


def sem_acento(texto):
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def normalizar(texto):
    """Minúsculas, sem acento, sem pontuação e sem espaço sobrando, para comparar nomes."""
    texto = sem_acento(texto or "").lower()
    texto = re.sub(r"[^a-z0-9 ]+", " ", texto)
    return " ".join(texto.split())


def limpar_telefone(bruto):
    """Devolve só os dígitos com DDD (10 ou 11), ou None se não der para aproveitar."""
    digitos = re.sub(r"\D", "", bruto or "")
    if len(digitos) in (12, 13) and digitos.startswith("55"):
        digitos = digitos[2:]
    if len(digitos) not in (10, 11):
        return None
    if not 11 <= int(digitos[:2]) <= 99:
        return None
    return digitos


def email_valido(email):
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email or ""))


def achar_coluna(cabecalho, candidatos):
    """Primeira coluna cujo título contém algum dos trechos, na ordem dada."""
    titulos = [normalizar(t) for t in cabecalho]
    for trecho in candidatos:
        alvo = normalizar(trecho)
        if not alvo:
            continue  # trecho vazio casaria com a primeira coluna
        for posicao, titulo in enumerate(titulos):
            if alvo in titulo:
                return posicao
    return None


def procurar_instituicao(texto, instituicoes):
    """Compara o que o aluno digitou com as instituições do BusKá.

    Devolve (id, situacao, sugestao). situacao: CERTA, PROVAVEL, REVISAR ou NENHUMA.
    """
    alvo = normalizar(texto)
    if not alvo:
        return None, "NENHUMA", ""
    nomes = {}
    for inst in instituicoes:
        nomes[normalizar(inst["nome"])] = inst
    if alvo in nomes:
        return nomes[alvo]["id"], "CERTA", nomes[alvo]["nome"]
    # O aluno costuma digitar só parte do nome oficial ("Faculdade Pitagoras"). Se todas as palavras
    # digitadas (2 ou mais) estão num nome só, esse é o provável, e vence o de menos palavras sobrando.
    palavras = set(alvo.split())
    contidos = []
    if len(palavras) >= 2:
        for nome_normalizado in nomes:
            palavras_do_nome = set(nome_normalizado.split())
            if palavras <= palavras_do_nome or palavras_do_nome <= palavras:
                contidos.append(nome_normalizado)
    if len(contidos) > 0:
        contidos.sort(key=lambda n: abs(len(n.split()) - len(palavras)))
        if len(contidos) == 1 or abs(len(contidos[0].split()) - len(palavras)) < abs(len(contidos[1].split()) - len(palavras)):
            return nomes[contidos[0]]["id"], "PROVAVEL", nomes[contidos[0]]["nome"]
        return None, "REVISAR", nomes[contidos[0]]["nome"]
    melhores = difflib.get_close_matches(alvo, list(nomes.keys()), n=1, cutoff=0.5)
    if not melhores:
        return None, "NENHUMA", ""
    nota = difflib.SequenceMatcher(None, alvo, melhores[0]).ratio()
    inst = nomes[melhores[0]]
    if nota >= CORTE_CERTO:
        return inst["id"], "CERTA", inst["nome"]
    if nota >= CORTE_PROVAVEL:
        return inst["id"], "PROVAVEL", inst["nome"]
    return None, "REVISAR", inst["nome"]


class Api:
    def __init__(self, url):
        self.base = url.rstrip("/") + "/v1"

    def chamar(self, metodo, caminho, token=None, corpo=None):
        dados = json.dumps(corpo).encode() if corpo is not None else None
        cabecalhos = {"Content-Type": "application/json"}
        if token:
            cabecalhos["Authorization"] = "Bearer " + token
        pedido = urllib.request.Request(self.base + caminho, method=metodo, data=dados, headers=cabecalhos)
        try:
            with urllib.request.urlopen(pedido, timeout=60) as resposta:
                return json.load(resposta)
        except urllib.error.HTTPError as erro:
            raise SystemExit(f"{metodo} {caminho} respondeu {erro.code}: {erro.read().decode()[:200]}")


def ler_linhas(caminho, args):
    with open(caminho, newline="", encoding="utf-8-sig") as arquivo:
        leitor = csv.reader(arquivo)
        cabecalho = next(leitor)
        linhas = list(leitor)
    colunas = {
        "nome": achar_coluna(cabecalho, [args.col_nome, "nome completo", "nome"]),
        "email": achar_coluna(cabecalho, [args.col_email, "quer usar", "e-mail", "email"]),
        "telefone": achar_coluna(cabecalho, [args.col_telefone, "telefone", "celular", "whatsapp"]),
        "instituicao": achar_coluna(cabecalho, [args.col_instituicao, "escola", "faculdade", "instituicao"]),
    }
    faltando = [nome for nome in ("nome", "email") if colunas[nome] is None]
    if faltando:
        raise SystemExit(f"Não achei a coluna de {', '.join(faltando)}. Cabeçalho do CSV: {cabecalho}")
    return cabecalho, colunas, linhas


def celula(linha, posicao):
    if posicao is None or posicao >= len(linha):
        return ""
    return linha[posicao].strip()


def conferir_linhas(linhas, colunas, instituicoes):
    """Uma entrada por linha do CSV, com os campos prontos e os avisos."""
    vistos = set()
    saida = []
    for numero, linha in enumerate(linhas, start=2):  # linha 1 é o cabeçalho
        nome = " ".join(celula(linha, colunas["nome"]).split())
        email = celula(linha, colunas["email"]).lower()
        telefone_bruto = celula(linha, colunas["telefone"])
        instituicao_texto = celula(linha, colunas["instituicao"])
        avisos = []
        erro = ""

        if not nome:
            erro = "nome vazio"
        elif len(nome) > 100:
            erro = "nome com mais de 100 caracteres"
        elif not email_valido(email):
            erro = "e-mail inválido"
        elif email in vistos:
            erro = "e-mail repetido no arquivo"
        vistos.add(email)

        telefone = limpar_telefone(telefone_bruto)
        if telefone_bruto and telefone is None:
            avisos.append("telefone ignorado (precisa de DDD e 10 ou 11 dígitos)")

        instituicao_id, situacao, sugestao = procurar_instituicao(instituicao_texto, instituicoes)
        if instituicao_texto and situacao == "PROVAVEL":
            avisos.append(f"instituição provável: {sugestao}")
        elif instituicao_texto and situacao == "REVISAR":
            avisos.append(f"instituição não confere (mais parecida: {sugestao})")
            instituicao_id = None
        elif instituicao_texto and situacao == "NENHUMA":
            avisos.append("instituição não cadastrada no BusKá")

        saida.append(
            {
                "linha": numero,
                "nome": nome,
                "email": email,
                "telefone": telefone,
                "instituicao_texto": instituicao_texto,
                "instituicao_id": instituicao_id,
                "instituicao_situacao": situacao if instituicao_texto else "",
                "erro": erro,
                "avisos": "; ".join(avisos),
                "resultado": "",
            }
        )
    return saida


def montar_convite(item):
    convite = {"nome": item["nome"], "email": item["email"]}
    if item["telefone"]:
        convite["telefone"] = item["telefone"]
    if item["instituicao_id"]:
        convite["instituicao_id"] = item["instituicao_id"]
    return convite


def enviar_convites(api, token, itens):
    for inicio in range(0, len(itens), TAMANHO_DO_LOTE):
        lote = itens[inicio : inicio + TAMANHO_DO_LOTE]
        resposta = api.chamar("POST", "/convites/", token, {"convites": [montar_convite(i) for i in lote]})
        resultados = resposta.get("items", resposta) if isinstance(resposta, dict) else resposta
        for item, resultado in zip(lote, resultados):
            texto = resultado.get("resultado", "")
            if resultado.get("motivo"):
                texto += f" ({resultado['motivo']})"
            item["resultado"] = texto


def gravar_relatorio(caminho, itens):
    campos = ["linha", "nome", "email", "telefone", "instituicao_texto", "instituicao_situacao", "erro", "avisos", "resultado"]
    with open(caminho, "w", newline="", encoding="utf-8") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=campos, extrasaction="ignore")
        escritor.writeheader()
        escritor.writerows(itens)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("csv", help="respostas do formulário exportadas em CSV")
    p.add_argument("--url", default="https://buska.lsd.ufcg.edu.br")
    p.add_argument("--enviar", action="store_true", help="cria os convites (sem isso só simula)")
    p.add_argument("--sim", action="store_true", help="não pede a confirmação digitada antes de enviar")
    p.add_argument("--col-nome", default="")
    p.add_argument("--col-email", default="")
    p.add_argument("--col-telefone", default="")
    p.add_argument("--col-instituicao", default="")
    args = p.parse_args()

    email = os.environ.get("BUSKA_GESTOR_EMAIL")
    senha = os.environ.get("BUSKA_GESTOR_SENHA")
    if not email or not senha:
        raise SystemExit("Defina BUSKA_GESTOR_EMAIL e BUSKA_GESTOR_SENHA (a conta do gestor que vai convidar).")

    _, colunas, linhas = ler_linhas(args.csv, args)
    api = Api(args.url)
    token = api.chamar("POST", "/auth/login", None, {"email": email, "password": senha})["token"]
    resposta = api.chamar("GET", "/instituicoes", token)
    instituicoes = resposta.get("items", resposta) if isinstance(resposta, dict) else resposta

    itens = conferir_linhas(linhas, colunas, instituicoes)
    prontos = [i for i in itens if not i["erro"]]
    com_erro = [i for i in itens if i["erro"]]
    sem_inst = [i for i in prontos if not i["instituicao_id"]]
    com_aviso = [i for i in prontos if i["avisos"]]

    print(f"Linhas no arquivo:           {len(itens)}")
    print(f"Prontas para convidar:       {len(prontos)}")
    print(f"  com instituição achada:    {len(prontos) - len(sem_inst)}")
    print(f"  sem instituição achada:    {len(sem_inst)} (o aluno escolhe no app)")
    print(f"  com algum aviso:           {len(com_aviso)}")
    print(f"Com erro (não serão criadas): {len(com_erro)}")
    for item in com_erro:
        print(f"  linha {item['linha']}: {item['erro']} ({item['email'] or item['nome'] or 'vazia'})")

    relatorio = re.sub(r"\.csv$", "", args.csv) + "-relatorio-" + datetime.datetime.now().strftime("%Y%m%d-%H%M") + ".csv"
    if not args.enviar:
        gravar_relatorio(relatorio, itens)
        print(f"\nSIMULAÇÃO: nada foi criado. Relatório em {relatorio}")
        print("Confira os avisos e rode de novo com --enviar.")
        return

    if not prontos:
        raise SystemExit("Nenhuma linha pronta para enviar.")
    if not args.sim:
        digitado = input(f"\nIsto vai criar {len(prontos)} convites e mandar e-mail aos alunos. Digite ENVIAR para continuar: ")
        if digitado.strip() != "ENVIAR":
            raise SystemExit("Cancelado, nada foi criado.")
    enviar_convites(api, token, prontos)
    gravar_relatorio(relatorio, itens)
    criados = sum(1 for i in prontos if i["resultado"].lower().startswith("criado"))
    print(f"\nResposta do BusKá registrada no relatório: {relatorio} ({criados} criados de {len(prontos)}).")


if __name__ == "__main__":
    sys.exit(main())
