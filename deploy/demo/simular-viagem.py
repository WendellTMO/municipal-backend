#!/usr/bin/env python3
"""Simula um ônibus andando, para mostrar o mapa da demo sem motorista nem GPS.

Cria o horário de agora e a viagem de hoje (se ainda não houver uma em andamento),
inicia como motorista e envia uma posição a cada poucos segundos pelas ruas, entre os
pontos da rota. Só usa a API pública, o mesmo caminho do app do motorista.

    python3 deploy/demo/simular-viagem.py
    python3 deploy/demo/simular-viagem.py --duracao 600 --finalizar

Quem estiver inscrito na rota e confirmado vê o ônibus na tela de localização.
"""
import argparse
import datetime
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DIAS = ["SEG", "TER", "QUA", "QUI", "SEX", "SAB", "DOM"]


class Api:
    def __init__(self, url):
        self.base = url.rstrip("/") + "/v1"

    def chamar(self, metodo, caminho, token=None, corpo=None):
        dados = None
        if corpo is not None:
            dados = json.dumps(corpo).encode()
        cabecalhos = {"Content-Type": "application/json"}
        if token:
            cabecalhos["Authorization"] = "Bearer " + token
        pedido = urllib.request.Request(
            self.base + caminho, method=metodo, data=dados, headers=cabecalhos
        )
        try:
            with urllib.request.urlopen(pedido, timeout=30) as resposta:
                return json.load(resposta)
        except urllib.error.HTTPError as erro:
            texto = erro.read().decode()[:200]
            raise RuntimeError(f"{metodo} {caminho} respondeu {erro.code}: {texto}")

    def entrar(self, email, senha):
        resposta = self.chamar("POST", "/auth/login", corpo={"email": email, "password": senha})
        return resposta["token"]


def distancia_m(a, b):
    """Distância em metros entre dois pontos (lat, lon), boa para trechos curtos."""
    metros_por_grau = 111_320
    dlat = (b[0] - a[0]) * metros_por_grau
    dlon = (b[1] - a[1]) * metros_por_grau * math.cos(math.radians(a[0]))
    return math.hypot(dlat, dlon)


def trilha_pelas_ruas(api, token, pontos):
    """Junta os trechos de rua entre pontos consecutivos numa lista de (lat, lon)."""
    trilha = []
    for i in range(len(pontos) - 1):
        a = pontos[i]
        b = pontos[i + 1]
        consulta = urllib.parse.urlencode(
            {"origin_lat": a[0], "origin_lng": a[1], "dest_lat": b[0], "dest_lng": b[1]}
        )
        try:
            trecho = api.chamar("GET", "/routing/route?" + consulta, token)["coordinates"]
            for c in trecho:
                trilha.append((c["latitude"], c["longitude"]))
        except RuntimeError:
            # Sem roteamento, vai em linha reta entre os dois pontos.
            trilha.append(a)
            trilha.append(b)
    return trilha


def reamostrar(trilha, quantidade):
    """Escolhe `quantidade` posições igualmente espaçadas ao longo da trilha."""
    acumulado = [0.0]
    for i in range(1, len(trilha)):
        acumulado.append(acumulado[-1] + distancia_m(trilha[i - 1], trilha[i]))
    total = acumulado[-1]
    if total == 0 or quantidade < 2:
        return [trilha[0]]

    resultado = []
    indice = 0
    for k in range(quantidade):
        alvo = total * k / (quantidade - 1)
        while indice < len(acumulado) - 2 and acumulado[indice + 1] < alvo:
            indice += 1
        trecho = acumulado[indice + 1] - acumulado[indice]
        fracao = 0.0
        if trecho > 0:
            fracao = (alvo - acumulado[indice]) / trecho
        a = trilha[indice]
        b = trilha[indice + 1]
        resultado.append((a[0] + (b[0] - a[0]) * fracao, a[1] + (b[1] - a[1]) * fracao))
    return resultado


def achar_rota(api, token, nome):
    rotas = api.chamar("GET", "/rotas", token)["items"]
    for rota in rotas:
        if rota["nome"] == nome:
            return rota
    nomes = ", ".join(r["nome"] for r in rotas)
    raise SystemExit(f"Rota '{nome}' não encontrada. Rotas: {nomes}")


def viagens_de_hoje(api, token, rota_id, status):
    hoje = datetime.date.today().isoformat()
    consulta = urllib.parse.urlencode(
        {"rota_id": rota_id, "data_inicio": hoje, "data_fim": hoje, "status": status}
    )
    return api.chamar("GET", "/viagens/?" + consulta, token)["items"]


def preparar_viagem(api, gestor, rota, sentido):
    """Devolve o id de uma viagem de hoje em andamento ou pronta para iniciar."""
    em_andamento = viagens_de_hoje(api, gestor, rota["id"], "EM_ANDAMENTO")
    if em_andamento:
        print("Já existe uma viagem em andamento nesta rota, vou reaproveitar.")
        return em_andamento[0]["id"], True

    agora = datetime.datetime.now().strftime("%H:%M")
    horarios = api.chamar("GET", f"/rotas/{rota['id']}/horarios", gestor)["items"]
    ja_existe = False
    for horario in horarios:
        if str(horario["horario_saida"])[:5] == agora:
            ja_existe = True
    if not ja_existe:
        api.chamar(
            "POST",
            f"/rotas/{rota['id']}/horarios",
            gestor,
            {"horario_saida": agora, "sentido": sentido, "dias": DIAS},
        )

    try:
        api.chamar("POST", "/viagens/gerar-lote", gestor, {"data": datetime.date.today().isoformat()})
    except RuntimeError as erro:
        print("gerar-lote:", erro)

    prontas = viagens_de_hoje(api, gestor, rota["id"], "AGENDADA")
    escolhida = None
    for viagem in prontas:
        if str(viagem["horario_inicio"])[:5] == agora:
            escolhida = viagem
    if escolhida is None:
        raise SystemExit("Não achei a viagem de agora. Confira a rota e os horários.")
    return escolhida["id"], False


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--url", default="https://buska.lsd.ufcg.edu.br")
    p.add_argument("--rota", default="ufcg -> galante (volta)")
    p.add_argument("--sentido", default="VOLTA", choices=["IDA", "VOLTA", "CIRCULAR"])
    p.add_argument("--duracao", type=int, default=300, help="segundos do percurso (padrão 300)")
    p.add_argument("--passo", type=int, default=3, help="segundos entre posições (padrão 3)")
    p.add_argument("--finalizar", action="store_true", help="finaliza a viagem no fim")
    p.add_argument("--gestor", default="gestor@buska.app")
    p.add_argument("--motorista", default="wendell@buska.app")
    p.add_argument("--senha", default="buska123")
    args = p.parse_args()

    api = Api(args.url)
    gestor = api.entrar(args.gestor, args.senha)
    motorista = api.entrar(args.motorista, args.senha)

    rota = achar_rota(api, gestor, args.rota)
    detalhe = api.chamar("GET", f"/rotas/{rota['id']}", gestor)
    pontos = []
    for ponto in detalhe["pontos"]:
        pontos.append((ponto["latitude"], ponto["longitude"]))
    if len(pontos) < 2:
        raise SystemExit("A rota precisa de pelo menos 2 pontos.")

    viagem_id, reaproveitada = preparar_viagem(api, gestor, rota, args.sentido)
    if not reaproveitada:
        api.chamar("PUT", f"/viagens/{viagem_id}/acao", motorista, {"acao": "INICIAR"})
        print("Viagem iniciada.")

    trilha = trilha_pelas_ruas(api, motorista, pontos)
    quantidade = max(2, args.duracao // args.passo)
    posicoes = reamostrar(trilha, quantidade)
    print(f"Enviando {len(posicoes)} posições, uma a cada {args.passo}s. Ctrl+C para parar.")

    for i, (lat, lon) in enumerate(posicoes):
        api.chamar(
            "POST", f"/viagens/{viagem_id}/localizacao", motorista, {"latitude": lat, "longitude": lon}
        )
        if i % 10 == 0:
            print(f"  {i + 1}/{len(posicoes)}  {lat:.5f}, {lon:.5f}")
        time.sleep(args.passo)

    if args.finalizar:
        api.chamar("PUT", f"/viagens/{viagem_id}/acao", motorista, {"acao": "FINALIZAR"})
        print("Viagem finalizada.")
    else:
        print("Fim do percurso. A viagem segue em andamento (use --finalizar para encerrar).")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
