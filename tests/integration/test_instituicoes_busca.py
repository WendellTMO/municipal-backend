from app.models.enum import TipoInstituicao
from app.models.geo import Instituicao
from app.services import instituicao_service


def _inst(_db, prefeitura, nome, sigla=None, codigo=None):
    inst = Instituicao(
        fonte="MANUAL",
        codigo_externo=codigo or nome[:25],
        nome=nome,
        sigla=sigla,
        tipo=TipoInstituicao.ESCOLA_PUBLICA,
        uf="PB",
        prefeitura_id=prefeitura.id,
    )
    _db.session.add(inst)
    _db.session.commit()
    return inst


def _nomes(resultado):
    return [i.nome for i in resultado]


def test_ignora_acento_e_maiuscula(_db, aluno, prefeitura):
    _inst(_db, prefeitura, "Universidade Estadual da Paraíba", "UEPB")
    _inst(_db, prefeitura, "Escola Municipal São José")

    assert _nomes(instituicao_service.buscar(str(aluno.user.id), "PARAIBA", 20)) == [
        "Universidade Estadual da Paraíba"
    ]
    assert _nomes(instituicao_service.buscar(str(aluno.user.id), "sao jose", 20)) == [
        "Escola Municipal São José"
    ]


def test_acha_pela_sigla(_db, aluno, prefeitura):
    _inst(_db, prefeitura, "Universidade Federal de Campina Grande", "UFCG")
    _inst(_db, prefeitura, "Escola Cidadã")

    assert _nomes(instituicao_service.buscar(str(aluno.user.id), "ufcg", 20)) == [
        "Universidade Federal de Campina Grande"
    ]


def test_todas_as_palavras_em_qualquer_ordem(_db, aluno, prefeitura):
    _inst(_db, prefeitura, "Universidade Federal de Campina Grande", "UFCG")
    _inst(_db, prefeitura, "Universidade Estadual da Paraíba", "UEPB")

    achadas = instituicao_service.buscar(str(aluno.user.id), "grande federal", 20)
    assert _nomes(achadas) == ["Universidade Federal de Campina Grande"]
    assert instituicao_service.buscar(str(aluno.user.id), "universidade xyz", 20) == []


def test_ordem_sigla_exata_depois_comeca_com_depois_contem(_db, aluno, prefeitura):
    _inst(_db, prefeitura, "Colégio Estadual Alfa")
    _inst(_db, prefeitura, "Alfa Centro de Ensino", "ACE")
    _inst(_db, prefeitura, "Instituto Federal", "ALFA")

    ordem = _nomes(instituicao_service.buscar(str(aluno.user.id), "alfa", 20))

    assert ordem == ["Instituto Federal", "Alfa Centro de Ensino", "Colégio Estadual Alfa"]


def test_desempate_pelo_nome_mais_curto_e_depois_alfabetico(_db, aluno, prefeitura):
    _inst(_db, prefeitura, "Escola Beta Grande")
    _inst(_db, prefeitura, "Escola Beta")
    _inst(_db, prefeitura, "Escola Alfa")

    ordem = _nomes(instituicao_service.buscar(str(aluno.user.id), "escola", 20))

    assert ordem == ["Escola Alfa", "Escola Beta", "Escola Beta Grande"]


def test_so_instituicoes_da_prefeitura_do_aluno(_db, aluno, prefeitura, other_prefeitura):
    _inst(_db, prefeitura, "Escola Daqui")
    _inst(_db, other_prefeitura, "Escola De Fora")

    assert _nomes(instituicao_service.buscar(str(aluno.user.id), "escola", 20)) == ["Escola Daqui"]


def test_respeita_o_limite(_db, aluno, prefeitura):
    for i in range(30):
        _inst(_db, prefeitura, f"Escola Numero {i:02d}", codigo=f"E{i}")

    assert len(instituicao_service.buscar(str(aluno.user.id), "escola", 5)) == 5


def test_texto_vazio_devolve_em_ordem_alfabetica(_db, aluno, prefeitura):
    _inst(_db, prefeitura, "Zeta")
    _inst(_db, prefeitura, "Alfa")

    assert _nomes(instituicao_service.buscar(str(aluno.user.id), "   ", 20)) == ["Alfa", "Zeta"]


def test_curinga_do_like_nao_casa_com_tudo(_db, aluno, prefeitura):
    _inst(_db, prefeitura, "Escola Um")
    _inst(_db, prefeitura, "Escola 100% Integral")

    assert _nomes(instituicao_service.buscar(str(aluno.user.id), "%", 20)) == [
        "Escola 100% Integral"
    ]
    assert instituicao_service.buscar(str(aluno.user.id), "_", 20) == []


def test_erro_de_digitacao_acha_o_parecido_so_quando_nao_ha_resultado_exato(_db, aluno, prefeitura):
    _inst(_db, prefeitura, "Universidade Federal de Campina Grande", "UFCG")
    _inst(_db, prefeitura, "Escola Municipal São José")

    assert _nomes(instituicao_service.buscar(str(aluno.user.id), "universidde federal", 20)) == [
        "Universidade Federal de Campina Grande"
    ]
    assert instituicao_service.buscar(str(aluno.user.id), "zzzzzz", 20) == []


def test_endpoint_devolve_so_o_que_a_lista_precisa(_db, aluno, prefeitura):
    _inst(_db, prefeitura, "Universidade Estadual da Paraíba", "UEPB")

    r = aluno.client.get("/v1/instituicoes/busca?q=paraiba&limit=5")

    assert r.status_code == 200
    corpo = r.get_json()
    assert corpo["total"] == 1
    assert set(corpo["items"][0]) == {"id", "nome", "sigla", "uf"}


def test_endpoint_valida_o_limite_e_exige_login(_db, aluno, client):
    assert aluno.client.get("/v1/instituicoes/busca?limit=999").status_code == 400
    assert aluno.client.get("/v1/instituicoes/busca?limit=0").status_code == 400
    assert client.get("/v1/instituicoes/busca?q=a").status_code in (401, 422)
