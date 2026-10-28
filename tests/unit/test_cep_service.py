import pytest
import requests

from app.core.exceptions import AppError, NotFoundError, RateLimitError, ValidationError
from app.services import cep_service


class _RespostaFalsa:
    def __init__(self, dados, status=200):
        self._dados = dados
        self._status = status

    def raise_for_status(self):
        if self._status >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        return self._dados


@pytest.fixture(autouse=True)
def _limpar_estado():
    cep_service._acessos_por_ip.clear()
    cep_service._cache_por_cep.clear()
    yield
    cep_service._acessos_por_ip.clear()
    cep_service._cache_por_cep.clear()


@pytest.fixture()
def viacep(monkeypatch):
    """Troca requests.get; guarda as URLs chamadas em `chamadas`."""
    estado = {"resposta": None, "erro": None, "chamadas": []}

    def falso_get(url, timeout=None):
        estado["chamadas"].append(url)
        assert timeout == 5
        if estado["erro"] is not None:
            raise estado["erro"]
        return estado["resposta"]

    monkeypatch.setattr(cep_service.requests, "get", falso_get)
    return estado


def test_sucesso_com_hifen(viacep):
    viacep["resposta"] = _RespostaFalsa(
        {"logradouro": "Rua A", "bairro": "Centro", "localidade": "Campina Grande", "uf": "PB"}
    )
    resultado = cep_service.consultar_cep("58429-900", "1.1.1.1")
    assert resultado == {
        "cep": "58429900",
        "logradouro": "Rua A",
        "bairro": "Centro",
        "cidade": "Campina Grande",
        "estado": "PB",
    }
    assert viacep["chamadas"] == ["https://viacep.com.br/ws/58429900/json/"]


def test_campos_ausentes_viram_vazio(viacep):
    viacep["resposta"] = _RespostaFalsa({"localidade": "Campina Grande", "uf": "PB"})
    resultado = cep_service.consultar_cep("58429900", "1.1.1.1")
    assert resultado["logradouro"] == ""
    assert resultado["bairro"] == ""


@pytest.mark.parametrize("cep", ["1234567", "123456789", "abcdefgh", "58429-90", "58-429900", ""])
def test_formato_invalido(viacep, cep):
    with pytest.raises(ValidationError):
        cep_service.consultar_cep(cep, "1.1.1.1")
    assert viacep["chamadas"] == []


@pytest.mark.parametrize("erro", [True, "true"])
def test_nao_encontrado(viacep, erro):
    viacep["resposta"] = _RespostaFalsa({"erro": erro})
    with pytest.raises(NotFoundError):
        cep_service.consultar_cep("99999999", "1.1.1.1")


@pytest.mark.parametrize(
    "erro",
    [requests.Timeout(), requests.ConnectionError()],
)
def test_indisponivel(viacep, erro):
    viacep["erro"] = erro
    with pytest.raises(AppError) as exc:
        cep_service.consultar_cep("58429900", "1.1.1.1")
    assert exc.value.status_code == 503


def test_indisponivel_http_500(viacep):
    viacep["resposta"] = _RespostaFalsa({}, status=500)
    with pytest.raises(AppError) as exc:
        cep_service.consultar_cep("58429900", "1.1.1.1")
    assert exc.value.status_code == 503


def test_limite_por_ip(viacep):
    viacep["resposta"] = _RespostaFalsa({"localidade": "X", "uf": "PB"})
    for _ in range(30):
        cep_service.consultar_cep("58429900", "1.1.1.1")
    with pytest.raises(RateLimitError):
        cep_service.consultar_cep("58429900", "1.1.1.1")
    # outro IP não é afetado
    cep_service.consultar_cep("58429900", "2.2.2.2")


def test_cache_evita_segunda_chamada(viacep):
    viacep["resposta"] = _RespostaFalsa({"localidade": "X", "uf": "PB"})
    cep_service.consultar_cep("58429900", "1.1.1.1")
    cep_service.consultar_cep("58429-900", "1.1.1.1")
    assert len(viacep["chamadas"]) == 1


def test_endpoint_publico_sem_jwt(app, viacep):
    viacep["resposta"] = _RespostaFalsa({"localidade": "X", "uf": "PB"})
    resposta = app.test_client().get("/v1/cep/58429-900")
    assert resposta.status_code == 200
    assert resposta.get_json()["cep"] == "58429900"
    assert app.test_client().get("/v1/cep/123").status_code == 400
