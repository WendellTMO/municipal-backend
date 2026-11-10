"""Rotas abertas a alunos de outras prefeituras, com foco em NÃO vazar dados entre prefeituras.

Cenário: a prefeitura dona da rota é `other_prefeitura` (P2). O aluno de fora é o `aluno`,
que pertence à `prefeitura` (P1). O gestor de P1 nunca enxerga a rota de P2.
"""

from datetime import date, timedelta

import pytest

from app.models.enum import SentidoViagem, StatusViagem
from app.models.geo import Instituicao, Ponto, TipoInstituicao
from app.models.rota import HorarioRota, Rota, RotaAluno, RotaPonto
from app.models.viagem import AlunosConfirmados, Viagem
from tests.factories.onibus_factory import OnibusFactory

pytestmark = pytest.mark.integration


@pytest.fixture()
def cenario_p2(_db, other_prefeitura, other_motorista):
    """Rota da P2 com um ponto de instituição, um horário de IDA e uma viagem de amanhã."""
    onibus = OnibusFactory(prefeitura_id=other_prefeitura.id)
    _db.session.add(onibus)
    _db.session.flush()
    rota = Rota(
        prefeitura_id=other_prefeitura.id,
        nome="Linha Universitária P2",
        motorista_padrao_id=other_motorista.user.id,
        veiculo_padrao_id=onibus.id,
    )
    _db.session.add(rota)
    ponto = Ponto(
        prefeitura_id=other_prefeitura.id, latitude=-7.2, longitude=-35.9, apelido="Campus P2"
    )
    _db.session.add(ponto)
    _db.session.flush()
    instituicao = Instituicao(
        fonte="MANUAL",
        codigo_externo="INST-P2",
        nome="Universidade da P2",
        tipo=TipoInstituicao.UNIVERSIDADE_PUBLICA,
        uf="PB",
        prefeitura_id=other_prefeitura.id,
        ponto_id=ponto.id,
    )
    _db.session.add(instituicao)
    _db.session.add(RotaPonto(rota_id=rota.id, ponto_id=ponto.id, ordem=1))
    horario = HorarioRota(rota_id=rota.id, horario_saida=__import__("datetime").time(7, 0), sentido=SentidoViagem.IDA)
    _db.session.add(horario)
    _db.session.flush()
    viagem = Viagem(
        data=date.today() + timedelta(days=1),
        horario_rota_id=horario.id,
        status=StatusViagem.AGENDADA,
        motorista_id=other_motorista.user.id,
    )
    _db.session.add(viagem)
    _db.session.commit()
    return {"rota": rota, "ponto": ponto, "instituicao": instituicao, "viagem": viagem}


def _abrir(_db, prefeitura, aberta=True):
    prefeitura.aceita_alunos_de_fora = aberta
    _db.session.commit()


def _ids(resp):
    return [item["id"] for item in resp.get_json()["items"]]


# ─── Fechada: nada vaza ─────────────────────────────────────────────────────


def test_prefeitura_fechada_nada_aparece_nem_abre_para_aluno_de_fora(aluno, cenario_p2):
    rota = cenario_p2["rota"]

    assert _ids(aluno.client.get("/v1/rotas/?incluir_outras=true")) == []
    assert aluno.client.get(f"/v1/rotas/{rota.id}").status_code == 403
    assert aluno.client.get(f"/v1/rotas/{rota.id}/pontos").status_code == 403
    assert aluno.client.get(f"/v1/rotas/{rota.id}/horarios").status_code == 403
    resp = aluno.client.post(f"/v1/rotas/{rota.id}/inscricao", json={"acao": "inscrever"})
    assert resp.status_code == 403


# ─── Aberta: só o que o aluno precisa ───────────────────────────────────────


def test_aberta_so_aparece_quando_o_aluno_pede_outras(_db, aluno, other_prefeitura, cenario_p2):
    _abrir(_db, other_prefeitura)

    sem = aluno.client.get("/v1/rotas/")
    com = aluno.client.get("/v1/rotas/?incluir_outras=true")

    assert _ids(sem) == []
    assert _ids(com) == [str(cenario_p2["rota"].id)]
    assert com.get_json()["items"][0]["municipio_nome"] == other_prefeitura.nome


def test_prefeitura_inativa_nao_aparece_mesmo_aberta(_db, aluno, other_prefeitura, cenario_p2):
    _abrir(_db, other_prefeitura)
    other_prefeitura.ativo = False
    _db.session.commit()

    assert _ids(aluno.client.get("/v1/rotas/?incluir_outras=true")) == []
    resp = aluno.client.post(
        f"/v1/rotas/{cenario_p2['rota'].id}/inscricao", json={"acao": "inscrever"}
    )
    assert resp.status_code == 403


def test_busca_por_nome_da_rota_do_municipio_e_uf(_db, aluno, other_prefeitura, cenario_p2):
    _abrir(_db, other_prefeitura)
    base = "/v1/rotas/?incluir_outras=true"

    assert len(_ids(aluno.client.get(f"{base}&q=universitaria"))) == 0  # sem acento não casa
    assert len(_ids(aluno.client.get(f"{base}&q=Universit"))) == 1
    assert len(_ids(aluno.client.get(f"{base}&q={other_prefeitura.nome[:4]}"))) == 1
    assert len(_ids(aluno.client.get(f"{base}&q=zzzz"))) == 0
    assert len(_ids(aluno.client.get(f"{base}&uf={other_prefeitura.estado}"))) == 1
    outra_uf = "AM" if other_prefeitura.estado != "AM" else "SP"
    assert len(_ids(aluno.client.get(f"{base}&uf={outra_uf}"))) == 0


def test_paginacao_das_rotas(_db, aluno, rota, other_prefeitura, cenario_p2):
    _abrir(_db, other_prefeitura)

    todas = _ids(aluno.client.get("/v1/rotas/?incluir_outras=true"))
    primeira = _ids(aluno.client.get("/v1/rotas/?incluir_outras=true&limit=1"))
    segunda = _ids(aluno.client.get("/v1/rotas/?incluir_outras=true&limit=1&offset=1"))

    assert len(todas) == 2
    assert primeira + segunda == todas


def test_rota_da_propria_prefeitura_vem_antes_mesmo_com_nome_depois(
    _db, aluno, rota, other_prefeitura, cenario_p2
):
    _abrir(_db, other_prefeitura)
    rota.nome = "ZZZ rota da casa"  # alfabeticamente depois da rota de fora
    _db.session.commit()

    ids = _ids(aluno.client.get("/v1/rotas/?incluir_outras=true"))

    assert ids == [str(rota.id), str(cenario_p2["rota"].id)]


def test_aluno_de_fora_inscreve_le_e_confirma_presenca(_db, aluno, other_prefeitura, cenario_p2):
    _abrir(_db, other_prefeitura)
    rota = cenario_p2["rota"]

    assert aluno.client.get(f"/v1/rotas/{rota.id}/pontos").status_code == 200
    assert aluno.client.get(f"/v1/rotas/{rota.id}/horarios").status_code == 200
    inscrever = aluno.client.post(f"/v1/rotas/{rota.id}/inscricao", json={"acao": "inscrever"})
    assert inscrever.status_code == 200, inscrever.get_data(as_text=True)

    assert str(rota.id) in _ids(aluno.client.get("/v1/rotas/me"))
    agenda = aluno.client.get("/v1/viagens/aluno/agenda").get_json()["items"]
    assert [v["viagem_id"] for v in agenda] == [str(cenario_p2["viagem"].id)]

    viagem_id = cenario_p2["viagem"].id
    ponto_id = str(cenario_p2["ponto"].id)
    sem_instituicao = aluno.client.put(
        f"/v1/viagens/{viagem_id}/confirmacao",
        json={"confirmacao": True, "ponto_embarque_id": ponto_id},
    )
    assert sem_instituicao.status_code == 400
    assert sem_instituicao.get_json()["error"]["details"]["field"] == "instituicao_id"

    com_instituicao = aluno.client.put(
        f"/v1/viagens/{viagem_id}/confirmacao",
        json={
            "confirmacao": True,
            "ponto_embarque_id": ponto_id,
            "instituicao_id": str(cenario_p2["instituicao"].id),
        },
    )
    assert com_instituicao.status_code == 200, com_instituicao.get_data(as_text=True)


def test_aluno_de_fora_nao_escreve_na_rota(_db, aluno, other_prefeitura, cenario_p2):
    _abrir(_db, other_prefeitura)
    rota = cenario_p2["rota"]
    aluno.client.post(f"/v1/rotas/{rota.id}/inscricao", json={"acao": "inscrever"})

    assert aluno.client.put(f"/v1/rotas/{rota.id}", json={"nome": "Invadida"}).status_code == 403
    assert aluno.client.delete(f"/v1/rotas/{rota.id}").status_code == 403
    assert (
        aluno.client.get(f"/v1/rotas/{rota.id}/instituicoes/ordem").status_code == 403
    )  # só gestor e motorista


def test_fechar_a_entrada_nao_expulsa_nem_prende_quem_ja_esta(
    _db, aluno, other_prefeitura, cenario_p2
):
    _abrir(_db, other_prefeitura)
    rota = cenario_p2["rota"]
    aluno.client.post(f"/v1/rotas/{rota.id}/inscricao", json={"acao": "inscrever"})
    _abrir(_db, other_prefeitura, aberta=False)

    assert aluno.client.get(f"/v1/rotas/{rota.id}/pontos").status_code == 200
    saida = aluno.client.post(f"/v1/rotas/{rota.id}/inscricao", json={"acao": "desinscrever"})
    assert saida.status_code == 200
    assert aluno.client.get(f"/v1/rotas/{rota.id}/pontos").status_code == 403


def test_aluno_de_uma_terceira_prefeitura_nao_entra_na_rota_fechada(
    _db, other_aluno, prefeitura, other_prefeitura, cenario_p2, rota
):
    # other_aluno é da P2 e enxerga a rota da P2, mas não a da P1 (que está fechada).
    assert other_aluno.client.get(f"/v1/rotas/{rota.id}").status_code == 403
    assert other_aluno.client.get(f"/v1/rotas/{cenario_p2['rota'].id}").status_code == 200


# ─── Gestor: abertura, isolamento e máscara ─────────────────────────────────


def test_so_gestor_liga_a_abertura_e_so_da_propria_prefeitura(
    _db, aluno, gestor, other_gestor, prefeitura, other_prefeitura
):
    assert aluno.client.patch(
        "/v1/rotas/abertura-municipal", json={"aceita_alunos_de_fora": True}
    ).status_code == 403

    resp = gestor.client.patch("/v1/rotas/abertura-municipal", json={"aceita_alunos_de_fora": True})

    assert resp.status_code == 200
    _db.session.expire_all()
    assert prefeitura.aceita_alunos_de_fora is True
    assert other_prefeitura.aceita_alunos_de_fora is False
    assert other_gestor.client.get("/v1/rotas/abertura-municipal").get_json() == {
        "aceita_alunos_de_fora": False
    }


def test_gestor_da_origem_nunca_ve_a_rota_da_outra_prefeitura(
    _db, gestor, other_prefeitura, cenario_p2
):
    _abrir(_db, other_prefeitura)
    rota = cenario_p2["rota"]

    assert gestor.client.get(f"/v1/rotas/{rota.id}").status_code == 403
    assert gestor.client.get(f"/v1/rotas/{rota.id}/pontos").status_code == 403
    assert _ids(gestor.client.get("/v1/rotas/?incluir_outras=true")) == []
    assert gestor.client.put(f"/v1/rotas/{rota.id}", json={"nome": "X"}).status_code == 403


def _confirmar_na_viagem(_db, viagem, aluno_user, ponto):
    _db.session.add(
        AlunosConfirmados(
            viagem_id=viagem.id,
            aluno_id=aluno_user.id,
            confirmacao=True,
            ponto_embarque_id=ponto.id,
            ponto_destino_id=ponto.id,
        )
    )
    _db.session.add(RotaAluno(rota_id=viagem.horario_rota.rota_id, aluno_id=aluno_user.id))
    _db.session.commit()


def test_gestor_dono_ve_o_aluno_de_fora_so_como_outro_municipio(
    _db, aluno, other_aluno, other_gestor, other_prefeitura, cenario_p2
):
    viagem, ponto = cenario_p2["viagem"], cenario_p2["ponto"]
    _confirmar_na_viagem(_db, viagem, aluno.user, ponto)
    _confirmar_na_viagem(_db, viagem, other_aluno.user, ponto)

    resp = other_gestor.client.get("/v1/viagens/")

    texto = resp.get_data(as_text=True)
    assert resp.status_code == 200
    # Nenhum dado do aluno de fora aparece para o gestor dono da rota.
    for segredo in (aluno.user.nome, aluno.user.email, aluno.user.cpf, str(aluno.user.id)):
        assert segredo not in texto
    alunos = resp.get_json()["items"][0]["alunos"]
    de_fora = [a for a in alunos if a["outro_municipio"]]
    da_casa = [a for a in alunos if not a["outro_municipio"]]
    assert len(de_fora) == 1 and len(da_casa) == 1
    assert de_fora[0]["nome"] == "Aluno de outro município"
    assert de_fora[0]["aluno_id"] is None
    assert de_fora[0]["instituicao"] is None
    assert da_casa[0]["nome"] == other_aluno.user.nome


def test_motorista_dono_ve_o_nome_do_aluno_de_fora_para_o_embarque(
    _db, aluno, other_motorista, cenario_p2
):
    _confirmar_na_viagem(_db, cenario_p2["viagem"], aluno.user, cenario_p2["ponto"])

    resp = other_motorista.client.get("/v1/viagens/minhas")

    alunos = resp.get_json()["items"][0]["alunos"]
    assert [a["nome"] for a in alunos] == [aluno.user.nome]
    assert alunos[0]["outro_municipio"] is False
    assert aluno.user.cpf not in resp.get_data(as_text=True)
    assert aluno.user.email not in resp.get_data(as_text=True)


def test_gestor_nao_ve_viagem_de_outra_prefeitura(_db, gestor, other_prefeitura, cenario_p2):
    _abrir(_db, other_prefeitura)

    resp = gestor.client.get("/v1/viagens/")

    assert resp.status_code == 200
    assert resp.get_json()["items"] == []


@pytest.mark.parametrize("consulta", ["limit=0", "limit=101", "offset=-1", "uf=PBX", "uf=P"])
def test_parametros_invalidos_das_rotas_sao_recusados(aluno, consulta):
    assert aluno.client.get(f"/v1/rotas/?{consulta}").status_code == 400
