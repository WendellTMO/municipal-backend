"""Convites de cadastro: /v1/convites."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest

from app.models.convite import ACEITO, CANCELADO, ENVIADO, EXPIRADO, PENDENTE, Convite
from app.models.enum import TipoInstituicao, UserStatus
from app.models.geo import Instituicao, Ponto
from app.models.rota import RotaAluno
from app.models.user import Aluno
from app.services import convite_service
from tests.factories.user_factory import AlunoFactory

pytestmark = pytest.mark.integration

CPF_A = "52998224725"
CPF_B = "11144477735"
ADULTO = "1990-05-20"


def _lote(gestor, convites):
    return gestor.client.post("/v1/convites/", json={"convites": convites})


def _enviar(_db, convite):
    """Faz o que o job de envio faz: gera link e PIN e marca ENVIADO."""
    token, pin = convite_service.gerar_token_e_pin(convite)
    convite.status = ENVIADO
    _db.session.commit()
    return token, pin


def _convite_enviado(_db, gestor, email="ana@exemplo.test", **extra):
    r = _lote(gestor, [{"nome": "Ana Souza", "email": email, **extra}])
    assert r.status_code == 201, r.get_data(as_text=True)
    convite = _db.session.get(Convite, r.get_json()["items"][0]["id"])
    return convite, *_enviar(_db, convite)


def _aceite(client, token, pin, **extra):
    corpo = {
        "pin": pin,
        "senha": "SenhaForte123",
        "cpf": CPF_A,
        "data_nascimento": ADULTO,
        "aceite_termos": True,
        **extra,
    }
    return client.post(f"/v1/convites/aceite/{token}", json=corpo)


def test_lote_com_linhas_validas_e_invalidas(gestor, aluno, other_prefeitura, _db):
    resp = _lote(
        gestor,
        [
            {"nome": "Ana", "email": "ana@exemplo.test"},
            {"nome": "Sem Email", "email": "invalido"},
            {"email": "semnome@exemplo.test"},
            {"nome": "Ja Tem Conta", "email": aluno.user.email},
            {"nome": "Repetido", "email": "ANA@exemplo.test"},
            {"nome": "Ponto Ruim", "email": "p@exemplo.test", "ponto_id": "nao-e-uuid"},
        ],
    )
    assert resp.status_code == 201
    itens = resp.get_json()["items"]
    resultados = [i["resultado"] for i in itens]
    assert resultados == ["CRIADO", "INVALIDO", "INVALIDO", "PULADO", "PULADO", "INVALIDO"]
    assert [i["linha"] for i in itens] == [1, 2, 3, 4, 5, 6]
    assert itens[0]["id"] is not None
    convite = _db.session.get(Convite, itens[0]["id"])
    assert convite.status == PENDENTE
    assert convite.token_hash is None and convite.pin_hash is None


def test_ids_de_outra_prefeitura_sao_invalidos(gestor, other_prefeitura, _db):
    inst = Instituicao(
        nome="Escola Alheia",
        tipo=TipoInstituicao.ESCOLA_PUBLICA,
        fonte="MANUAL",
        codigo_externo="x",
        uf="PB",
        prefeitura_id=other_prefeitura.id,
    )
    _db.session.add(inst)
    _db.session.commit()
    resp = _lote(gestor, [{"nome": "A", "email": "a@exemplo.test", "instituicao_id": str(inst.id)}])
    assert resp.get_json()["items"][0]["resultado"] == "INVALIDO"


def test_lote_vazio_e_acima_do_limite(gestor):
    assert _lote(gestor, []).status_code == 400
    muitos = [{"nome": "A", "email": f"a{i}@exemplo.test"} for i in range(501)]
    assert _lote(gestor, muitos).status_code == 400


def test_convite_expirado_e_renovado(gestor, _db):
    convite, _, _ = _convite_enviado(_db, gestor)
    convite.expira_em = datetime.now(UTC) - timedelta(minutes=1)
    _db.session.commit()
    resp = _lote(gestor, [{"nome": "Ana Nova", "email": "ana@exemplo.test"}])
    item = resp.get_json()["items"][0]
    assert item["resultado"] == "RENOVADO"
    assert item["id"] == str(convite.id)
    _db.session.refresh(convite)
    assert convite.status == PENDENTE and convite.nome == "Ana Nova"


def test_listar_filtra_por_status_e_marca_expirados(gestor, _db):
    convite, _, _ = _convite_enviado(_db, gestor)
    _lote(gestor, [{"nome": "Bia", "email": "bia@exemplo.test"}])
    convite.expira_em = datetime.now(UTC) - timedelta(minutes=1)
    _db.session.commit()

    todos = gestor.client.get("/v1/convites/").get_json()
    assert todos["total"] == 2
    assert "token_hash" not in todos["items"][0] and "pin_hash" not in todos["items"][0]
    expirados = gestor.client.get("/v1/convites/?status=EXPIRADO").get_json()
    assert [i["email"] for i in expirados["items"]] == ["ana@exemplo.test"]
    assert gestor.client.get("/v1/convites/?status=XYZ").status_code == 400


def test_listagem_sem_n_mais_1(gestor, _db, query_counter):
    _lote(gestor, [{"nome": f"N{i}", "email": f"n{i}@exemplo.test"} for i in range(3)])
    with query_counter() as pequeno:
        gestor.client.get("/v1/convites/")
    _lote(gestor, [{"nome": f"M{i}", "email": f"m{i}@exemplo.test"} for i in range(30)])
    with query_counter() as grande:
        gestor.client.get("/v1/convites/")
    assert grande.count == pequeno.count


def test_criacao_em_lote_sem_n_mais_1(gestor, _db, query_counter):
    with query_counter() as pequeno:
        _lote(gestor, [{"nome": f"N{i}", "email": f"n{i}@exemplo.test"} for i in range(2)])
    with query_counter() as grande:
        _lote(gestor, [{"nome": f"M{i}", "email": f"m{i}@exemplo.test"} for i in range(40)])
    assert grande.count <= pequeno.count + 2


def test_reenviar_volta_para_fila_e_invalida_link_antigo(gestor, client, _db):
    convite, token, pin = _convite_enviado(_db, gestor)
    resp = gestor.client.post(f"/v1/convites/{convite.id}/reenviar")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == PENDENTE
    r = client.post(f"/v1/convites/aceite/{token}/validar", json={"pin": pin})
    assert r.status_code == 404


def test_cancelar_e_conflito_ao_repetir(gestor, client, _db):
    convite, token, pin = _convite_enviado(_db, gestor)
    assert gestor.client.delete(f"/v1/convites/{convite.id}").status_code == 200
    _db.session.refresh(convite)
    assert convite.status == CANCELADO
    assert gestor.client.delete(f"/v1/convites/{convite.id}").status_code == 409
    assert gestor.client.post(f"/v1/convites/{convite.id}/reenviar").status_code == 409
    assert client.post(f"/v1/convites/aceite/{token}/validar", json={"pin": pin}).status_code == 404


def test_autorizacao(client, aluno, other_gestor, gestor, _db):
    assert client.get("/v1/convites/").status_code == 401
    assert aluno.client.get("/v1/convites/").status_code == 403
    assert _lote(aluno, [{"nome": "A", "email": "a@exemplo.test"}]).status_code == 403

    convite, _, _ = _convite_enviado(_db, gestor)
    assert other_gestor.client.get("/v1/convites/").get_json()["total"] == 0
    assert other_gestor.client.delete(f"/v1/convites/{convite.id}").status_code == 404
    assert other_gestor.client.post(f"/v1/convites/{convite.id}/reenviar").status_code == 404


def test_validar_pin_certo_devolve_dados_e_termos(gestor, client, _db):
    convite, token, pin = _convite_enviado(_db, gestor, telefone="83999998888")
    r = client.post(f"/v1/convites/aceite/{token}/validar", json={"pin": pin})
    assert r.status_code == 200
    corpo = r.get_json()
    assert corpo["email"] == "ana@exemplo.test"
    assert corpo["nome"] == "Ana Souza"
    assert corpo["termos_texto"] == convite_service.TERMOS_DE_USO_TEXTO


def test_pin_errado_conta_tentativas_e_bloqueia_na_quinta(gestor, client, _db):
    _, token, pin = _convite_enviado(_db, gestor)
    url = f"/v1/convites/aceite/{token}/validar"
    for restantes in (4, 3, 2, 1):
        r = client.post(url, json={"pin": "000000x"})
        assert r.status_code == 400
        assert r.get_json()["error"]["details"] == {"tentativas_restantes": restantes}
        assert "dados" not in r.get_json()
    assert client.post(url, json={"pin": "000000x"}).status_code == 429
    # Bloqueado: nem o PIN certo passa.
    assert client.post(url, json={"pin": pin}).status_code == 429


def test_token_invalido_igual_a_expirado(gestor, client, _db):
    convite, token, pin = _convite_enviado(_db, gestor)
    convite.expira_em = datetime.now(UTC) - timedelta(seconds=1)
    _db.session.commit()
    expirado = client.post(f"/v1/convites/aceite/{token}/validar", json={"pin": pin})
    inexistente = client.post("/v1/convites/aceite/nao-existe/validar", json={"pin": pin})
    assert expirado.status_code == inexistente.status_code == 404
    assert expirado.get_json()["error"]["message"] == inexistente.get_json()["error"]["message"]
    assert client.post("/v1/convites/aceite/nao-existe", json={}).status_code in (400, 404)


def test_convite_pendente_nao_aceita_token_nenhum(gestor, client, _db):
    r = _lote(gestor, [{"nome": "Ana", "email": "ana@exemplo.test"}])
    assert r.status_code == 201
    assert (
        client.post("/v1/convites/aceite/qualquer/validar", json={"pin": "123456"}).status_code
        == 404
    )


def test_aceite_maior_de_idade_cria_aluno_ativo_com_ponto_e_rota(
    gestor, client, ponto, rota, rota_ponto, _db
):
    convite, token, pin = _convite_enviado(
        _db, gestor, ponto_id=str(ponto.id), rota_id=str(rota.id)
    )
    r = _aceite(client, token, pin, telefone="(83) 99999-8888")
    assert r.status_code == 201, r.get_data(as_text=True)
    assert r.get_json()["status"] == "ACTIVE"

    aluno = _db.session.get(Aluno, r.get_json()["id"])
    assert aluno.status == UserStatus.ACTIVE
    assert aluno.signup_completed_at is not None
    assert aluno.ponto_casa_id is None
    assert aluno.cpf == CPF_A and aluno.telefone == "83999998888"
    assert aluno.prefeitura_id == gestor.user.prefeitura_id
    inscricao = RotaAluno.query.filter_by(rota_id=rota.id, aluno_id=aluno.id).one()
    assert inscricao.ponto_embarque_padrao_id == ponto.id
    _db.session.refresh(convite)
    assert convite.status == ACEITO and convite.aluno_id == aluno.id
    assert convite.termos_versao == convite_service.TERMOS_DE_USO_VERSAO

    login = client.post(
        "/v1/auth/login", json={"email": "ana@exemplo.test", "password": "SenhaForte123"}
    )
    assert login.status_code == 200
    # O link não serve duas vezes.
    assert _aceite(client, token, pin).status_code == 404


def test_lote_valida_ponto_contra_a_rota(gestor, prefeitura, ponto, rota, rota_ponto, _db):
    fora = Ponto(prefeitura_id=prefeitura.id, latitude=-7.2, longitude=-35.9, apelido="Fora")
    _db.session.add(fora)
    _db.session.commit()
    resp = _lote(
        gestor,
        [
            {
                "nome": "A",
                "email": "a@exemplo.test",
                "rota_id": str(rota.id),
                "ponto_id": str(ponto.id),
            },
            {
                "nome": "B",
                "email": "b@exemplo.test",
                "rota_id": str(rota.id),
                "ponto_id": str(fora.id),
            },
            {"nome": "C", "email": "c@exemplo.test", "ponto_id": str(ponto.id)},
        ],
    )
    itens = resp.get_json()["items"]
    assert [i["resultado"] for i in itens] == ["CRIADO", "INVALIDO", "INVALIDO"]
    assert "não pertence" in itens[1]["motivo"]
    assert "exige uma rota" in itens[2]["motivo"]


def test_validar_pin_devolve_ponto_id_e_apelido(gestor, client, ponto, rota, rota_ponto, _db):
    _, token, pin = _convite_enviado(_db, gestor, ponto_id=str(ponto.id), rota_id=str(rota.id))
    dados = client.post(f"/v1/convites/aceite/{token}/validar", json={"pin": pin}).get_json()
    assert dados["ponto_id"] == str(ponto.id)
    assert dados["ponto_apelido"] == ponto.apelido


def test_aceite_ignora_ponto_que_saiu_da_rota(gestor, client, ponto, rota, rota_ponto, _db):
    _, token, pin = _convite_enviado(_db, gestor, ponto_id=str(ponto.id), rota_id=str(rota.id))
    _db.session.delete(rota_ponto)
    _db.session.commit()
    r = _aceite(client, token, pin)
    assert r.status_code == 201
    inscricao = RotaAluno.query.filter_by(rota_id=rota.id, aluno_id=r.get_json()["id"]).one()
    assert inscricao.ponto_embarque_padrao_id is None


def test_aceite_menor_segue_fluxo_do_responsavel(gestor, client, _db):
    _, token, pin = _convite_enviado(_db, gestor)
    nascimento = date.today().replace(year=date.today().year - 15).isoformat()
    sem_responsavel = _aceite(client, token, pin, data_nascimento=nascimento)
    assert sem_responsavel.status_code == 400

    with patch("app.services.aluno_service.send_email") as enviar:
        r = _aceite(
            client,
            token,
            pin,
            data_nascimento=nascimento,
            nome_responsavel="Mae da Ana",
            email_responsavel="mae@exemplo.test",
        )
    assert r.status_code == 201, r.get_data(as_text=True)
    assert r.get_json()["status"] == "PENDING_SIGNUP"
    assert r.get_json()["requer_consentimento_responsavel"] is True
    assert enviar.call_args.kwargs["to"] == "mae@exemplo.test"
    aluno = _db.session.get(Aluno, r.get_json()["id"])
    assert aluno.guardian_token is not None


def test_aceite_sem_aceitar_termos(gestor, client, _db):
    _, token, pin = _convite_enviado(_db, gestor)
    assert _aceite(client, token, pin, aceite_termos=False).status_code == 400


def test_aceite_com_cpf_duplicado(gestor, client, aluno, _db):
    aluno.user.cpf = CPF_A
    _db.session.commit()
    _, token, pin = _convite_enviado(_db, gestor)
    r = _aceite(client, token, pin)
    assert r.status_code == 409
    assert r.get_json()["error"]["field"] == "cpf"


def test_aceite_com_email_que_virou_conta(gestor, client, _db):
    _, token, pin = _convite_enviado(_db, gestor)
    conta = AlunoFactory(prefeitura_id=gestor.user.prefeitura_id, email="ana@exemplo.test")
    _db.session.add(conta)
    _db.session.commit()
    r = _aceite(client, token, pin)
    assert r.status_code == 409
    assert r.get_json()["error"]["field"] == "email"


def test_aceite_com_pin_errado_nao_cria_conta(gestor, client, _db):
    _, token, _ = _convite_enviado(_db, gestor)
    assert _aceite(client, token, "999999x").status_code == 400
    assert Aluno.query.filter_by(email="ana@exemplo.test").count() == 0


def test_expirar_marca_status(gestor, _db):
    convite, _, _ = _convite_enviado(_db, gestor)
    convite.expira_em = datetime.now(UTC) - timedelta(seconds=1)
    _db.session.commit()
    gestor.client.get("/v1/convites/")
    _db.session.refresh(convite)
    assert convite.status == EXPIRADO
