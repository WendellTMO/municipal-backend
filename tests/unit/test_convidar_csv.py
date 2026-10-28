import pytest

from scripts import convidar_csv

PONTOS_POR_ROTA = {
    "r1": [{"id": "p1", "apelido": "Ponto da Praça"}, {"id": "p2", "apelido": "Ponto Central"}],
    "r2": [{"id": "p3", "apelido": "Outro Ponto"}],
}
INSTITUICOES = [{"id": "i1", "nome": "Escola Exemplo"}]
ROTAS = [{"id": "r1", "nome": "Rota Exemplo"}, {"id": "r2", "nome": "Rota Exemplo"}]


def test_ler_csv_normaliza_cabecalho_e_ignora_linha_vazia(tmp_path):
    arquivo = tmp_path / "a.csv"
    arquivo.write_text(" Nome ,EMAIL,telefone\n Ana ,ana@exemplo.test,\n,,\n", encoding="utf-8")
    assert convidar_csv.ler_csv(str(arquivo)) == [
        {"nome": "Ana", "email": "ana@exemplo.test", "telefone": ""}
    ]


def test_ler_csv_exige_nome_e_email(tmp_path):
    arquivo = tmp_path / "a.csv"
    arquivo.write_text("nome,telefone\nAna,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="email"):
        convidar_csv.ler_csv(str(arquivo))


def test_exemplo_do_repositorio_e_valido():
    linhas = convidar_csv.ler_csv("scripts/exemplo_convites.csv")
    assert len(linhas) == 3


def test_montar_itens_resolve_ponto_entre_os_pontos_da_rota():
    linhas = [
        {
            "nome": "Ana",
            "email": "a@exemplo.test",
            "ponto": "ponto da praça",
            "instituicao": "Escola Exemplo",
            "rota": "r1",
        },
        {"nome": "Bia", "email": "b@exemplo.test", "ponto": "p2", "rota": "r1"},
    ]
    resultado = convidar_csv.montar_itens(linhas, PONTOS_POR_ROTA, INSTITUICOES, ROTAS)
    assert resultado[0] == (
        2,
        {
            "nome": "Ana",
            "email": "a@exemplo.test",
            "ponto_id": "p1",
            "instituicao_id": "i1",
            "rota_id": "r1",
        },
        "",
    )
    assert resultado[1][1]["ponto_id"] == "p2"


def test_montar_itens_ponto_sem_rota_ou_fora_da_rota_e_invalido():
    linhas = [
        {"nome": "Ana", "email": "a@exemplo.test", "ponto": "Ponto da Praça"},
        {"nome": "Bia", "email": "b@exemplo.test", "ponto": "Ponto da Praça", "rota": "r2"},
    ]
    resultado = convidar_csv.montar_itens(linhas, PONTOS_POR_ROTA, INSTITUICOES, ROTAS)
    assert resultado[0][1] is None and "exige a coluna rota" in resultado[0][2]
    assert resultado[1][1] is None and "não encontrado" in resultado[1][2]


def test_montar_itens_aponta_nao_encontrado_e_ambiguo():
    linhas = [
        {"nome": "Ana", "email": "a@exemplo.test", "ponto": "Inexistente", "rota": "r1"},
        {"nome": "Bia", "email": "b@exemplo.test", "rota": "Rota Exemplo"},
    ]
    resultado = convidar_csv.montar_itens(linhas, PONTOS_POR_ROTA, INSTITUICOES, ROTAS)
    assert resultado[0][1] is None and "não encontrado" in resultado[0][2]
    assert resultado[1][1] is None and "mais de um" in resultado[1][2]


def test_dividir_em_lotes_de_500():
    lotes = convidar_csv.dividir_em_lotes(list(range(1201)))
    assert [len(lote) for lote in lotes] == [500, 500, 201]


def test_dry_run_nao_chama_o_post(tmp_path, monkeypatch, capsys):
    arquivo = tmp_path / "a.csv"
    arquivo.write_text("nome,email\nAna,ana@exemplo.test\n", encoding="utf-8")
    monkeypatch.setenv("BUSKA_API_URL", "http://api.test")
    monkeypatch.setenv("BUSKA_EMAIL", "g@exemplo.test")
    monkeypatch.setenv("BUSKA_SENHA", "x")
    monkeypatch.setattr(convidar_csv, "fazer_login", lambda *a: {})
    monkeypatch.setattr(convidar_csv, "listar", lambda *a: [])

    def nao_deve_chamar(*a):
        raise AssertionError("POST chamado no dry-run")

    monkeypatch.setattr(convidar_csv, "enviar_lote", nao_deve_chamar)
    assert convidar_csv.main([str(arquivo), "--dry-run"]) == 0
    assert "dry-run: convidaria ana@exemplo.test" in capsys.readouterr().out
