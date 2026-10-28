"""Cria o gestor, o motorista e um ônibus da demo, sem apagar nem sobrescrever nada.

Uso (dentro do container da API, com o script montado):
    python scripts/criar_equipe_demo.py --prefeitura-ibge 2504009 \
        --gestor-email gestor@buska.app --gestor-senha SENHA \
        --motorista-email wendell@buska.app --motorista-senha SENHA

Roda de novo sem problema: o que já existe é mantido.
"""

import argparse

from werkzeug.security import generate_password_hash

from app import create_app
from app.models.base import db
from app.models.enum import UserRole, UserStatus
from app.models.onibus import Onibus
from app.models.prefeitura import Prefeitura
from app.models.user import Gestor, Motorista, User

# CPFs e CNH de teste, só para preencher campos obrigatórios e únicos
CPF_GESTOR = "39053344705"
CPF_MOTORISTA = "16899535009"
CNH_MOTORISTA = "88888888802"
PLACA_ONIBUS = "BUS0D30"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefeitura-ibge", required=True)
    parser.add_argument("--gestor-email", required=True)
    parser.add_argument("--gestor-senha", required=True)
    parser.add_argument("--motorista-email", required=True)
    parser.add_argument("--motorista-senha", required=True)
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        prefeitura = Prefeitura.query.filter_by(codigo_ibge=args.prefeitura_ibge).first()
        if prefeitura is None:
            raise SystemExit(f"Prefeitura {args.prefeitura_ibge} não encontrada.")

        if User.query.filter_by(email=args.gestor_email).first() is None:
            db.session.add(
                Gestor(
                    prefeitura_id=prefeitura.id,
                    nome="Gestor Demonstração",
                    email=args.gestor_email,
                    senha_hash=generate_password_hash(args.gestor_senha),
                    cpf=CPF_GESTOR,
                    telefone="83999990000",
                    role=UserRole.GESTOR,
                    status=UserStatus.ACTIVE,
                )
            )
            print("Gestor criado:", args.gestor_email)
        else:
            print("Gestor já existe:", args.gestor_email)

        if User.query.filter_by(email=args.motorista_email).first() is None:
            db.session.add(
                Motorista(
                    prefeitura_id=prefeitura.id,
                    nome="Wendell Motorista",
                    email=args.motorista_email,
                    senha_hash=generate_password_hash(args.motorista_senha),
                    cpf=CPF_MOTORISTA,
                    telefone="83999990001",
                    role=UserRole.MOTORISTA,
                    status=UserStatus.ACTIVE,
                    cnh=CNH_MOTORISTA,
                )
            )
            print("Motorista criado:", args.motorista_email)
        else:
            print("Motorista já existe:", args.motorista_email)

        if Onibus.query.filter_by(placa=PLACA_ONIBUS).first() is None:
            db.session.add(
                Onibus(
                    prefeitura_id=prefeitura.id,
                    placa=PLACA_ONIBUS,
                    modelo="Ônibus da demonstração",
                    capacidade=40,
                )
            )
            print("Ônibus criado:", PLACA_ONIBUS)
        else:
            print("Ônibus já existe:", PLACA_ONIBUS)

        db.session.commit()


if __name__ == "__main__":
    main()
