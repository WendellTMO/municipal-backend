# instituicao_parsers.py

from flask_restx import reqparse

instituicao_list_parser = reqparse.RequestParser()
instituicao_list_parser.add_argument(
    "search",
    type=str,
    required=False,
    help="Pesquisa por nome, sigla e/ou UF",
)

instituicao_list_parser.add_argument(
    "limit",
    type=int,
    required=False,
    default=10,
    help="Limite de resultados",
)

instituicao_busca_parser = reqparse.RequestParser()
instituicao_busca_parser.add_argument(
    "q",
    type=str,
    required=False,
    help="Texto da busca: nome ou sigla, sem diferenciar acento nem maiúscula (máx. 100)",
)
instituicao_busca_parser.add_argument(
    "limit",
    type=int,
    required=False,
    default=20,
    help="Quantidade de resultados (1 a 50, padrão 20)",
)

parsers = {
    "instituicao_list": instituicao_list_parser,
    "instituicao_busca": instituicao_busca_parser,
}
