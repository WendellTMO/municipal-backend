import importlib.util
import pathlib

caminho = pathlib.Path(__file__).with_name("importar-convites.py")
spec = importlib.util.spec_from_file_location("importar_convites", caminho)
imp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(imp)

INSTITUICOES = [
    {"id": "9", "nome": "Faculdade Pitagoras de Campina Grande"},
    {"id": "8", "nome": "FACULDADE DE CAMPINA GRANDE"},
    {"id": "1", "nome": "UNIVERSIDADE ESTADUAL DA PARAÍBA"},
    {"id": "2", "nome": "CENTRO UNIVERSITÁRIO FACISA"},
    {"id": "3", "nome": "EEEFM CAIC JOSE JOFILLY"},
]


def test_normalizar_ignora_acento_caixa_e_pontuacao():
    assert imp.normalizar("  Universidade   Estadual da Paraíba! ") == "universidade estadual da paraiba"


def test_telefone_aceita_ddd_e_tira_o_55():
    assert imp.limpar_telefone("(83) 99999-9999") == "83999999999"
    assert imp.limpar_telefone("+55 83 3333-4444") == "8333334444"
    assert imp.limpar_telefone("99999-9999") is None
    assert imp.limpar_telefone("") is None
    assert imp.limpar_telefone("(05) 99999-9999") is None


def test_instituicao_igual_com_outra_grafia_e_certa():
    inst_id, situacao, _ = imp.procurar_instituicao("universidade estadual da paraiba", INSTITUICOES)
    assert (inst_id, situacao) == ("1", "CERTA")


def test_instituicao_parecida_e_provavel_e_diferente_vai_para_revisao():
    inst_id, situacao, _ = imp.procurar_instituicao("Universidade Estadual Paraiba UEPB", INSTITUICOES)
    assert situacao in ("PROVAVEL", "REVISAR")
    inst_id, situacao, _ = imp.procurar_instituicao("Colégio Totalmente Outro", INSTITUICOES)
    assert (inst_id, situacao) == (None, "NENHUMA")


def test_conferir_linhas_barra_erro_duplicado_e_telefone_ruim():
    colunas = {"nome": 0, "email": 1, "telefone": 2, "instituicao": 3}
    linhas = [
        ["Ana Souza", "ana@exemplo.test", "(83) 98888-7777", "Centro Universitário FACISA"],
        ["Ana Duplicada", "ANA@exemplo.test", "", ""],
        ["", "sem-nome@exemplo.test", "", ""],
        ["Beto", "email-ruim", "", ""],
        ["Caio", "caio@exemplo.test", "123", "Escola que não existe"],
    ]
    itens = imp.conferir_linhas(linhas, colunas, INSTITUICOES)
    assert itens[0]["erro"] == "" and itens[0]["instituicao_id"] == "2" and itens[0]["telefone"] == "83988887777"
    assert itens[1]["erro"] == "e-mail repetido no arquivo"
    assert itens[2]["erro"] == "nome vazio"
    assert itens[3]["erro"] == "e-mail inválido"
    assert itens[4]["erro"] == "" and itens[4]["telefone"] is None and "telefone ignorado" in itens[4]["avisos"]
    assert itens[4]["instituicao_id"] is None


def test_montar_convite_so_leva_o_que_existe():
    item = {"nome": "Ana", "email": "a@b.test", "telefone": None, "instituicao_id": None}
    assert imp.montar_convite(item) == {"nome": "Ana", "email": "a@b.test"}


def test_achar_coluna_ignora_trecho_vazio_e_prefere_a_ordem_dada():
    cabecalho = ["Carimbo de data/hora", "Endereço de e-mail", "Nome completo", "E-mail que você quer usar no BusKá"]
    assert imp.achar_coluna(cabecalho, ["", "quer usar", "e-mail"]) == 3
    assert imp.achar_coluna(cabecalho, ["", "e-mail"]) == 1
    assert imp.achar_coluna(cabecalho, ["", "telefone"]) is None


def test_nome_digitado_pela_metade_acha_o_oficial():
    inst_id, situacao, nome = imp.procurar_instituicao("Faculdade Pitagoras", INSTITUICOES)
    assert (inst_id, situacao) == ("9", "PROVAVEL")
    # Mais de um nome contém as palavras: não escolhe sozinho.
    inst_id, situacao, _ = imp.procurar_instituicao("Faculdade Campina", INSTITUICOES)
    assert inst_id is None or situacao == "PROVAVEL"
