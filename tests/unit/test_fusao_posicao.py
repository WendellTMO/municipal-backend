from app.utils.fusao_posicao import fundir_leituras, suavizar

# Perto de Campina Grande: 0.0001 grau de latitude tem cerca de 11 metros.
LAT = -7.2300
LON = -35.8800


def _leitura(deslocamento_lat=0.0, precisao=10.0):
    return {"lat": LAT + deslocamento_lat, "lon": LON, "precisao": precisao}


def test_leitura_imprecisa_e_descartada():
    assert fundir_leituras([_leitura(precisao=80)], None) is None


def test_media_pesa_mais_a_leitura_precisa():
    lat, lon, precisao = fundir_leituras(
        [_leitura(0.0, precisao=5), _leitura(0.0004, precisao=20)], None
    )

    # A leitura de 5 m pesa 16 vezes mais que a de 20 m.
    assert abs(lat - LAT) < 0.00004
    assert precisao < 5


def test_aluno_que_desceu_fica_de_fora_com_tres_ou_mais_leituras():
    leituras = [_leitura(0.0), _leitura(0.00005), _leitura(0.0001), _leitura(0.05)]

    lat, lon, _ = fundir_leituras(leituras, None)

    assert abs(lat - LAT) < 0.0002


def test_duas_leituras_distantes_ficam_com_a_mais_proxima_da_posicao_anterior():
    leituras = [_leitura(0.0), _leitura(0.05)]

    lat, lon, _ = fundir_leituras(leituras, (LAT + 0.049, LON))

    assert abs(lat - (LAT + 0.05)) < 0.0001


def test_primeira_leitura_vira_a_posicao():
    assert suavizar(None, (LAT, LON), 10, 5) == (LAT, LON)


def test_salto_impossivel_e_rejeitado_mas_depois_de_2_minutos_recomeca():
    anterior = (LAT, LON)
    longe = (LAT + 0.05, LON)

    assert suavizar(anterior, longe, 10, 10) is None
    assert suavizar(anterior, longe, 10, 300) is not None


def test_onibus_parado_nao_treme():
    anterior = (LAT, LON)

    assert suavizar(anterior, (LAT + 0.00003, LON), 10, 10) == anterior


def test_movimento_normal_anda_em_direcao_a_nova_leitura():
    anterior = (LAT, LON)
    nova = (LAT + 0.0010, LON)

    lat, _ = suavizar(anterior, nova, 10, 10)

    assert LAT < lat < nova[0]
