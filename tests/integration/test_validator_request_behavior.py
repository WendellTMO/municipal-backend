"""Request-level behaviour of the phone and CPF validators.

These validators are wired into two different layers:

* ``app/schemas/validators.py`` runs inside Marshmallow schemas, so its errors
  are reported as field errors (generic message + ``details`` keyed by field).
* ``app/utils/validators.py`` runs inside the service layer, so its errors are
  reported as application errors (the text is carried in ``message``).

Both layers are reachable in production on different endpoints, and the two
response shapes are part of the public API. A plain import-level check cannot
tell them apart, so these tests drive real HTTP requests.
"""

import pytest

# CPF that passes the check-digit algorithm.
VALID_CPF = "52998224725"
# CPF with a valid length but a wrong first check digit.
INVALID_CPF = "11122233344"


def _signup_payload(**overrides):
    """Signup body that is valid except for whatever the test overrides."""
    payload = {
        "nome": "Aluno Teste",
        "email": "aluno-validator@buska.test",
        "password": "StrongPass123!",
        "cpf": VALID_CPF,
        "telefone": "83999999999",
        "matricula": "2024001",
        "instituicao_id": "11111111-1111-4111-8111-111111111111",
        "data_nascimento": "2000-01-01",
        "endereco_casa": {
            "logradouro": "Rua Teste",
            "numero": "100",
            "bairro": "Centro",
            "cidade": "Campina Grande",
            "cep": "58400000",
            "latitude": -7.23,
            "longitude": -35.88,
        },
    }
    payload.update(overrides)
    return payload


def _errors(response):
    return (response.get_json() or {}).get("error", {})


@pytest.mark.integration
def test_signup_rejects_phone_with_invalid_ddd(client):
    """A bad area code must be rejected during the request.

    The message is asserted verbatim because it is what distinguishes the
    schema-layer phone validator from the service-layer one.
    """
    r = client.post("/v1/alunos/signup", json=_signup_payload(telefone="0912345678"))

    assert r.status_code == 400, r.get_data(as_text=True)
    details = _errors(r).get("details", {})
    assert "telefone" in details, details
    assert "Telefone DDD inválido (deve estar entre 11 e 99)" in details["telefone"]


@pytest.mark.integration
def test_signup_rejects_phone_with_wrong_digit_count(client):
    r = client.post("/v1/alunos/signup", json=_signup_payload(telefone="123"))

    assert r.status_code == 400, r.get_data(as_text=True)
    details = _errors(r).get("details", {})
    assert "telefone" in details, details
    assert "Telefone deve conter 10 ou 11 dígitos (com DDD)" in details["telefone"]


@pytest.mark.integration
@pytest.mark.parametrize("telefone", ["83999999999", "(83) 99999-9999", "8332210000", None])
def test_signup_accepts_valid_or_absent_phone(client, telefone):
    """Accepted phones must never produce a ``telefone`` field error."""
    r = client.post("/v1/alunos/signup", json=_signup_payload(telefone=telefone))

    assert "telefone" not in _errors(r).get("details", {})


@pytest.mark.integration
def test_signup_reports_invalid_cpf_as_a_field_error(client):
    """Schema layer: generic message, offending text nested under ``details``."""
    r = client.post("/v1/alunos/signup", json=_signup_payload(cpf=INVALID_CPF))

    assert r.status_code == 400, r.get_data(as_text=True)
    error = _errors(r)
    assert error.get("code") == "VALIDATION_ERROR"
    assert error.get("message") == "Erro de validação"
    assert "cpf" in error.get("details", {}), error


@pytest.mark.integration
def test_create_motorista_reports_invalid_cpf_in_the_message(gestor):
    """Service layer: the offending text is carried in ``message`` instead.

    ``MotoristaCreateRequestSchema`` declares ``cpf`` without a validator, so
    this route is the one place where the service-layer CPF check is the only
    guard and its response shape is observable.
    """
    payload = {
        "nome": "Motorista Teste",
        "email": "motorista-validator@buska.test",
        "password": "StrongPass123!",
        "cpf": INVALID_CPF,
        "telefone": "83999999999",
        "cnh": "12345678900",
    }

    r = gestor.client.post("/v1/users/motoristas", json=payload)

    assert r.status_code == 400, r.get_data(as_text=True)
    error = _errors(r)
    assert error.get("code") == "VALIDATION_ERROR"
    assert error.get("message") == "CPF inválido (primeiro dígito verificador)"
    assert "details" not in error, error


@pytest.mark.integration
def test_signup_nao_exige_matricula(client):
    """Matrícula é opcional: sem ela, o cadastro passa da validação do corpo."""
    payload = _signup_payload()
    del payload["matricula"]

    r = client.post("/v1/alunos/signup", json=payload)

    assert "matricula" not in str(_errors(r))
