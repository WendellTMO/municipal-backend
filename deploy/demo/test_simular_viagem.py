import importlib.util
import pathlib

caminho = pathlib.Path(__file__).with_name("simular-viagem.py")
spec = importlib.util.spec_from_file_location("simular_viagem", caminho)
sim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sim)


def test_reamostrar_mantem_extremos_e_quantidade():
    trilha = [(0.0, 0.0), (0.0, 0.01), (0.01, 0.01)]
    posicoes = sim.reamostrar(trilha, 5)
    assert len(posicoes) == 5
    assert posicoes[0] == trilha[0]
    assert posicoes[-1] == trilha[-1]


def test_reamostrar_espaca_igualmente():
    trilha = [(0.0, 0.0), (0.0, 0.02)]
    posicoes = sim.reamostrar(trilha, 3)
    assert abs(posicoes[1][1] - 0.01) < 1e-9
