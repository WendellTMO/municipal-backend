"""Demo: junta as posições que vários alunos a bordo mandam numa só posição do ônibus.

Técnicas usadas por apps de trânsito: descarta leitura imprecisa, fica com o grupo da maioria,
pondera cada leitura pelo inverso do quadrado do erro e suaviza o resultado.
"""

import math
import statistics

from app.utils.geo_utils import calcular_distancia_metros

PRECISAO_MAXIMA_M = 50
PRECISAO_MINIMA_M = 3
RAIO_DO_GRUPO_M = 100
VELOCIDADE_MAXIMA_MS = 40
RAIO_PARADO_M = 8
# Depois desse tempo sem posição aceita, um salto grande deixa de ser tratado como erro.
SEGUNDOS_PARA_RECOMECAR = 120


def _distancia(a: dict, b: dict) -> float:
    return calcular_distancia_metros(a["lat"], a["lon"], b["lat"], b["lon"])


def _escolher_grupo(boas: list[dict], anterior: tuple[float, float] | None) -> list[dict]:
    """Fica com as leituras que concordam. Quem desceu e continua compartilhando fica de fora."""
    if len(boas) == 1:
        return boas
    if len(boas) == 2:
        if _distancia(boas[0], boas[1]) <= 150:
            return boas
        if anterior is not None:
            ponto = {"lat": anterior[0], "lon": anterior[1]}
            return [min(boas, key=lambda r: _distancia(r, ponto))]
        return [min(boas, key=lambda r: r["precisao"])]

    centro = {
        "lat": statistics.median([r["lat"] for r in boas]),
        "lon": statistics.median([r["lon"] for r in boas]),
    }
    grupo = []
    for leitura in boas:
        if _distancia(leitura, centro) <= RAIO_DO_GRUPO_M:
            grupo.append(leitura)
    if not grupo:
        return [min(boas, key=lambda r: r["precisao"])]
    return grupo


def fundir_leituras(
    leituras: list[dict], anterior: tuple[float, float] | None
) -> tuple[float, float, float] | None:
    """leituras: dicts com lat, lon e precisao (metros). Devolve (lat, lon, precisao) ou None."""
    boas = []
    for leitura in leituras:
        if leitura["precisao"] <= PRECISAO_MAXIMA_M:
            boas.append(leitura)
    if not boas:
        return None

    grupo = _escolher_grupo(boas, anterior)
    soma_pesos = 0.0
    soma_lat = 0.0
    soma_lon = 0.0
    for leitura in grupo:
        precisao = max(leitura["precisao"], PRECISAO_MINIMA_M)
        peso = 1.0 / (precisao * precisao)
        soma_pesos += peso
        soma_lat += leitura["lat"] * peso
        soma_lon += leitura["lon"] * peso
    return soma_lat / soma_pesos, soma_lon / soma_pesos, math.sqrt(1.0 / soma_pesos)


def suavizar(
    anterior: tuple[float, float] | None,
    nova: tuple[float, float],
    precisao: float,
    segundos: float,
) -> tuple[float, float] | None:
    """Posição final do ônibus. None quando a nova leitura é impossível (salto de ônibus)."""
    if anterior is None:
        return nova
    distancia = calcular_distancia_metros(anterior[0], anterior[1], nova[0], nova[1])
    if segundos <= SEGUNDOS_PARA_RECOMECAR:
        velocidade = distancia / max(segundos, 1.0)
        if velocidade > VELOCIDADE_MAXIMA_MS:
            return None
    # Parado: o GPS oscila alguns metros e o ônibus não deve tremer no mapa.
    if distancia < RAIO_PARADO_M:
        return anterior
    # Leitura precisa puxa mais a posição para o novo valor.
    peso = 0.7 if precisao <= 20 else 0.5
    return (
        anterior[0] + peso * (nova[0] - anterior[0]),
        anterior[1] + peso * (nova[1] - anterior[1]),
    )
