"""
BusKa Database Seed Script

Creates initial test data for development and testing.
Also supports importing Prefeituras and Instituicoes from CSV files.
"""

import os
from datetime import UTC, date, datetime, time, timedelta

from werkzeug.security import generate_password_hash

from app import create_app
from app.models.base import db
from app.models.enum import (
    SentidoViagem,
    StatusOcorrencia,
    StatusViagem,
    TipoInstituicao,
    TipoOcorrencia,
    UserRole,
    UserStatus,
)
from app.models.geo import Instituicao, Ponto
from app.models.notificacao import Notificacao
from app.models.ocorrencia import Ocorrencia
from app.models.onibus import Onibus
from app.models.prefeitura import Prefeitura
from app.models.rota import HorarioRota, Rota, RotaAluno, RotaPonto
from app.models.user import Aluno, Gestor, Motorista
from app.models.viagem import AlunosConfirmados, Viagem
from scripts.seeds.instituicoes_importer import import_escolas_csv, import_ies_csv
from scripts.seeds.prefeituras_importer import import_prefeituras_csv

app = create_app()
TEST_PASSWORD = "buska123"


# ─────────────────────────────────────────────────────────────────────────────
# CSV catalog helpers
# ─────────────────────────────────────────────────────────────────────────────


def should_import_prefeituras() -> bool:
    return (
        db.session.query(Prefeitura.id).filter(Prefeitura.codigo_ibge.isnot(None)).first() is None
    )


def should_import_instituicoes() -> bool:
    return (
        db.session.query(Instituicao.id).filter(Instituicao.fonte.in_(("EMEC", "INEP"))).first()
        is None
    )


def seed_catalog_from_csv() -> None:
    municipios_csv_path = os.getenv("MUNICIPIOS_CSV_PATH")
    ies_csv_path = os.getenv("IES_CSV_PATH")
    escolas_csv_path = os.getenv("ESCOLAS_CSV_PATH")

    print("\n" + "=" * 50)
    print("Catalog Import")
    print("=" * 50)

    if should_import_prefeituras():
        if municipios_csv_path:
            print(f"Importing prefeituras from: {municipios_csv_path}")
            total = import_prefeituras_csv(municipios_csv_path)
            print(f"Prefeituras imported/updated: {total}")
        else:
            print("MUNICIPIOS_CSV_PATH not provided. Skipping.")
    else:
        print("Prefeituras already imported. Skipping.")

    if should_import_instituicoes():
        if ies_csv_path:
            print(f"Importing IES from: {ies_csv_path}")
            total = import_ies_csv(ies_csv_path)
            print(f"IES imported/updated: {total}")
        else:
            print("IES_CSV_PATH not provided. Skipping.")

        if escolas_csv_path:
            print(f"Importing schools from: {escolas_csv_path}")
            total = import_escolas_csv(escolas_csv_path)
            print(f"Schools imported/updated: {total}")
        else:
            print("ESCOLAS_CSV_PATH not provided. Skipping.")
    else:
        print("Instituicoes already imported. Skipping.")

    print("Catalog import finished.\n")


# ─────────────────────────────────────────────────────────────────────────────
# Demo seed helpers
# ─────────────────────────────────────────────────────────────────────────────


def _ponto(prefeitura_id, lat, lon, apelido):
    p = Ponto(prefeitura_id=prefeitura_id, latitude=lat, longitude=lon, apelido=apelido)
    db.session.add(p)
    return p


def _motorista(prefeitura_id, nome, email, cpf, telefone, cnh, pw_hash):
    m = Motorista(
        prefeitura_id=prefeitura_id,
        nome=nome,
        email=email,
        senha_hash=pw_hash,
        cpf=cpf,
        telefone=telefone,
        role=UserRole.MOTORISTA,
        status=UserStatus.ACTIVE,
        cnh=cnh,
    )
    db.session.add(m)
    return m


def _aluno(
    prefeitura_id,
    nome,
    email,
    cpf,
    telefone,
    pw_hash,
    matricula,
    instituicao_id,
    ponto_casa_id,
    status=UserStatus.ACTIVE,
    nome_responsavel=None,
    cpf_responsavel=None,
    email_responsavel=None,
    guardian_consented_at=None,
    data_nascimento=None,
):
    a = Aluno(
        prefeitura_id=prefeitura_id,
        nome=nome,
        email=email,
        senha_hash=pw_hash,
        cpf=cpf,
        telefone=telefone,
        role=UserRole.ALUNO,
        status=status,
        matricula=matricula,
        instituicao_id=instituicao_id,
        ponto_casa_id=ponto_casa_id,
        nome_responsavel=nome_responsavel,
        cpf_responsavel=cpf_responsavel,
        email_responsavel=email_responsavel,
        guardian_consented_at=guardian_consented_at,
        data_nascimento=data_nascimento,
    )
    db.session.add(a)
    return a


def _onibus(prefeitura_id, placa, modelo, capacidade):
    o = Onibus(prefeitura_id=prefeitura_id, placa=placa, modelo=modelo, capacidade=capacidade)
    db.session.add(o)
    return o


def _rota(prefeitura_id, nome, motorista, onibus):
    r = Rota(
        prefeitura_id=prefeitura_id,
        nome=nome,
        motorista_padrao_id=motorista.id,
        veiculo_padrao_id=onibus.id,
    )
    db.session.add(r)
    return r


def _horario(rota, horario_saida, sentido):
    h = HorarioRota(rota_id=rota.id, horario_saida=horario_saida, sentido=sentido)
    db.session.add(h)
    return h


def _viagem(horario, motorista, onibus, data, status, inicio_real=None, fim_real=None):
    v = Viagem(
        data=data,
        horario_rota_id=horario.id,
        motorista_id=motorista.id,
        veiculo_id=onibus.id,
        status=status,
        inicio_real=inicio_real,
        fim_real=fim_real,
    )
    db.session.add(v)
    return v


def _confirmar(viagem, aluno, ponto_embarque, confirmado=True):
    ac = AlunosConfirmados(
        viagem_id=viagem.id,
        aluno_id=aluno.id,
        confirmacao=confirmado,
        ponto_embarque_id=ponto_embarque.id,
    )
    db.session.add(ac)
    return ac


def _notificacao(usuario_id, titulo, mensagem, lida=True, dias_atras=0):
    dt = datetime.now(UTC) - timedelta(days=dias_atras)
    n = Notificacao(
        usuario_id=usuario_id,
        titulo=titulo,
        mensagem=mensagem,
        enviada=lida,
        data_envio=dt,
    )
    db.session.add(n)
    return n


def _ocorrencia(autor_id, viagem_id, tipo, descricao, status=StatusOcorrencia.ABERTA):
    o = Ocorrencia(
        autor_id=autor_id,
        viagem_id=viagem_id,
        tipo=tipo,
        descricao=descricao,
        status=status,
    )
    db.session.add(o)
    return o


# ─────────────────────────────────────────────────────────────────────────────
# Main demo data
# ─────────────────────────────────────────────────────────────────────────────


APELIDO_UFCG = "UFCG — Campus I (Rua Aprígio Veloso)"
APELIDO_UEPB = "UEPB — Campus I (Baraúnas)"
APELIDO_CESG = "CESG — Escola Estadual Assis Chateaubriand"

# (nome, tipo, apelido do ponto onde a instituição fica)
INSTITUICOES_DEMO = [
    (
        "Universidade Federal de Campina Grande (UFCG)",
        TipoInstituicao.UNIVERSIDADE_PUBLICA,
        APELIDO_UFCG,
    ),
    (
        "Universidade Estadual da Paraíba (UEPB)",
        TipoInstituicao.UNIVERSIDADE_PUBLICA,
        APELIDO_UEPB,
    ),
    (
        "CESG - Escola Estadual Assis Chateaubriand",
        TipoInstituicao.ESCOLA_PUBLICA,
        APELIDO_CESG,
    ),
]


def _get_instituicao(nome):
    return db.session.query(Instituicao).filter_by(nome=nome).first()


def vincular_instituicoes_aos_pontos(pref) -> None:
    """Cria ou reaponta cada instituição demo para o ponto de rota correto.

    Idempotente: pode rodar de novo em banco já semeado.
    """
    for nome, tipo, apelido in INSTITUICOES_DEMO:
        ponto = db.session.query(Ponto).filter_by(prefeitura_id=pref.id, apelido=apelido).first()
        if ponto is None:
            continue
        inst = _get_instituicao(nome)
        if inst is None:
            inst = Instituicao(
                nome=nome,
                tipo=tipo,
                fonte="MANUAL_DEMO",
                codigo_externo=str(abs(hash(nome)) % 10_000_000),
                uf="PB",
                prefeitura_id=pref.id,
                situacao="ATIVA",
                categoria_administrativa="Pública",
            )
            db.session.add(inst)
        inst.ponto_id = ponto.id
    db.session.flush()


def seed_demo_data() -> None:
    print("\n" + "=" * 50)
    print("BusKa Demo Seed — Campina Grande, PB")
    print("=" * 50 + "\n")

    # Idempotency: skip if gestor already seeded
    if db.session.query(Gestor).filter_by(email="admin@buska.app").first():
        print("Demo data already exists. Skipping.\n")
        pref_existente = db.session.query(Prefeitura).filter_by(codigo_ibge="2504009").first()
        if pref_existente:
            vincular_instituicoes_aos_pontos(pref_existente)
            db.session.commit()
        return

    pw = generate_password_hash(TEST_PASSWORD)
    today = date.today()

    # ── 1. Prefeitura ─────────────────────────────────────────────────────────
    pref = db.session.query(Prefeitura).filter(Prefeitura.codigo_ibge == "2504009").first()
    if not pref:
        raise Exception(
            "Campina Grande (IBGE 2504009) not found. "
            "Run with MUNICIPIOS_CSV_PATH to import prefeituras first, "
            "or ensure the CSV import ran."
        )
    print(f"Using prefeitura: {pref.nome}")

    # ── 2. Gestor ─────────────────────────────────────────────────────────────
    gestor = Gestor(
        prefeitura_id=pref.id,
        nome="Maria das Graças Silva",
        email="admin@buska.app",
        senha_hash=pw,
        cpf="12345678901",
        telefone="83999990001",
        role=UserRole.GESTOR,
        status=UserStatus.ACTIVE,
    )
    db.session.add(gestor)

    # ── 3. Pontos de referência (CG reais) ────────────────────────────────────
    print("Creating geographic points...")

    # Instituições
    p_ufcg = _ponto(pref.id, -7.21676, -35.90820, APELIDO_UFCG)
    p_uepb = _ponto(pref.id, -7.23260, -35.89430, APELIDO_UEPB)
    _ponto(pref.id, -7.22140, -35.88790, APELIDO_CESG)

    # Terminais / pontos centrais
    p_terminal = _ponto(pref.id, -7.23050, -35.88090, "Terminal de Integração CG")
    p_catole = _ponto(pref.id, -7.24510, -35.92010, "Praça do Açude — Bairro Catole")
    p_bodocongo = _ponto(pref.id, -7.21960, -35.93760, "Av. Manoel Tavares — Bodocongó")
    p_liberdade = _ponto(pref.id, -7.21170, -35.90310, "Av. Floriano Peixoto — Liberdade")
    p_jose_pin = _ponto(pref.id, -7.22660, -35.87450, "Rua Cônego Rolim — José Pinheiro")
    p_mirande = _ponto(pref.id, -7.28950, -35.95200, "Praça Central — Galante (distrito)")
    p_queimadas = _ponto(pref.id, -7.61860, -35.90050, "Terminal Rodoviário — Queimadas")
    p_cruz_armas = _ponto(pref.id, -7.23800, -35.88300, "Cruz das Armas — CG")
    _ponto(pref.id, -7.20680, -35.89490, "Av. Dinamarca — Pedregal")
    p_prata = _ponto(pref.id, -7.23770, -35.87980, "Bairro Prata — CG")

    # Casas dos alunos (pontos de embarque individuais)
    casas = [
        _ponto(pref.id, -7.24200, -35.91800, "Res. Ana Carla — Catole"),
        _ponto(pref.id, -7.22100, -35.93500, "Res. Bruno — Bodocongó"),
        _ponto(pref.id, -7.21500, -35.90000, "Res. Camila — Liberdade"),
        _ponto(pref.id, -7.22900, -35.87600, "Res. Daniel — José Pinheiro"),
        _ponto(pref.id, -7.29100, -35.95400, "Res. Elaine — Galante"),
        _ponto(pref.id, -7.61700, -35.89900, "Res. Felipe — Queimadas"),
        _ponto(pref.id, -7.23600, -35.88100, "Res. Gabriela — Cruz das Armas"),
        _ponto(pref.id, -7.20800, -35.89600, "Res. Hugo — Pedregal"),
        _ponto(pref.id, -7.23900, -35.88000, "Res. Isabela — Prata"),
        _ponto(pref.id, -7.24600, -35.92100, "Res. João — Catole"),
        _ponto(pref.id, -7.21800, -35.93800, "Res. Karen — Bodocongó"),
        _ponto(pref.id, -7.21100, -35.90200, "Res. Lucas — Liberdade"),
        _ponto(pref.id, -7.22700, -35.87500, "Res. Mariana — José Pinheiro"),
        _ponto(pref.id, -7.29200, -35.95100, "Res. Nathan — Galante"),
        _ponto(pref.id, -7.62000, -35.90100, "Res. Olivia — Queimadas"),
        _ponto(pref.id, -7.23900, -35.88200, "Res. Pedro — Cruz das Armas"),
        _ponto(pref.id, -7.20700, -35.89700, "Res. Quinn — Pedregal"),
        _ponto(pref.id, -7.23800, -35.87900, "Res. Renata — Prata"),
        _ponto(pref.id, -7.24400, -35.91900, "Res. Samuel — Catole"),
        _ponto(pref.id, -7.22000, -35.93600, "Res. Tânia — Bodocongó"),
    ]

    db.session.flush()

    # ── 4. Instituições ───────────────────────────────────────────────────────
    print("Creating institutions...")

    vincular_instituicoes_aos_pontos(pref)
    ufcg = _get_instituicao(INSTITUICOES_DEMO[0][0])
    uepb = _get_instituicao(INSTITUICOES_DEMO[1][0])

    # ── 5. Ônibus ─────────────────────────────────────────────────────────────
    print("Creating fleet...")

    bus1 = _onibus(pref.id, "PBX1A34", "Mercedes-Benz Sprinter 515", 30)
    bus2 = _onibus(pref.id, "PBX5B78", "Volare W9 Escolar", 44)
    bus3 = _onibus(pref.id, "PBX9C12", "Volkswagen 15.190 EOD", 35)
    bus4 = _onibus(pref.id, "PBX3D56", "Marcopolo Viale", 40)

    # ── 6. Motoristas ─────────────────────────────────────────────────────────
    print("Creating drivers...")

    mot1 = _motorista(
        pref.id,
        "Carlos Eduardo Amorim",
        "carlos@buska.app",
        "45678912301",
        "83999880001",
        "01234567890",
        pw,
    )
    mot2 = _motorista(
        pref.id,
        "Silvio Dantas de Oliveira",
        "silvio@buska.app",
        "56789012302",
        "83999880002",
        "09876543211",
        pw,
    )
    mot3 = _motorista(
        pref.id,
        "Rosângela Feitosa Lima",
        "rosangela@buska.app",
        "67890123403",
        "83999880003",
        "11223344551",
        pw,
    )

    db.session.flush()

    # ── 7. Rotas com pontos ───────────────────────────────────────────────────
    print("Creating routes...")

    # Rota A: Galante → UFCG (IDA)
    rota_a = _rota(pref.id, "Galante → UFCG (Manhã)", mot1, bus1)
    db.session.flush()
    for ordem, ponto in enumerate([p_mirande, p_catole, p_terminal, p_ufcg], 1):
        db.session.add(RotaPonto(rota_id=rota_a.id, ponto_id=ponto.id, ordem=ordem))
    hor_a_ida = _horario(rota_a, time(5, 30), SentidoViagem.IDA)

    # Rota B: Bodocongó → UEPB (IDA)
    rota_b = _rota(pref.id, "Bodocongó → UEPB (Manhã)", mot2, bus2)
    db.session.flush()
    for ordem, ponto in enumerate([p_bodocongo, p_liberdade, p_uepb], 1):
        db.session.add(RotaPonto(rota_id=rota_b.id, ponto_id=ponto.id, ordem=ordem))
    hor_b_ida = _horario(rota_b, time(6, 0), SentidoViagem.IDA)

    # Rota C: Queimadas → UFCG (IDA)
    rota_c = _rota(pref.id, "Queimadas → UFCG (Manhã)", mot3, bus3)
    db.session.flush()
    for ordem, ponto in enumerate([p_queimadas, p_cruz_armas, p_terminal, p_ufcg], 1):
        db.session.add(RotaPonto(rota_id=rota_c.id, ponto_id=ponto.id, ordem=ordem))
    hor_c_ida = _horario(rota_c, time(5, 0), SentidoViagem.IDA)

    # Rota D: José Pinheiro → UFCG + UEPB (CIRCULAR, tarde)
    rota_d = _rota(pref.id, "José Pinheiro → UFCG/UEPB (Tarde)", mot1, bus4)
    db.session.flush()
    for ordem, ponto in enumerate([p_jose_pin, p_prata, p_ufcg, p_uepb], 1):
        db.session.add(RotaPonto(rota_id=rota_d.id, ponto_id=ponto.id, ordem=ordem))
    hor_d_tarde = _horario(rota_d, time(12, 30), SentidoViagem.IDA)

    db.session.flush()

    # ── 8. Alunos (20) ───────────────────────────────────────────────────────
    print("Creating 20 students...")

    nomes = [
        (
            "Ana Carla Bezerra",
            "aluno01@buska.app",
            "11111111101",
            "83988010001",
            "2024001",
            ufcg.id,
        ),
        ("Bruno Sousa Melo", "aluno02@buska.app", "22222222202", "83988010002", "2024002", ufcg.id),
        (
            "Camila Torres Lima",
            "aluno03@buska.app",
            "33333333303",
            "83988010003",
            "2024003",
            uepb.id,
        ),
        (
            "Daniel Rocha Neto",
            "aluno04@buska.app",
            "44444444404",
            "83988010004",
            "2024004",
            ufcg.id,
        ),
        (
            "Elaine Vasconcelos",
            "aluno05@buska.app",
            "55555555505",
            "83988010005",
            "2024005",
            ufcg.id,
        ),
        (
            "Felipe Araújo Costa",
            "aluno06@buska.app",
            "66666666606",
            "83988010006",
            "2024006",
            ufcg.id,
        ),
        (
            "Gabriela Cunha Dias",
            "aluno07@buska.app",
            "77777777707",
            "83988010007",
            "2024007",
            uepb.id,
        ),
        (
            "Hugo Ferreira Braga",
            "aluno08@buska.app",
            "88888888808",
            "83988010008",
            "2024008",
            uepb.id,
        ),
        (
            "Isabela Martins Paz",
            "aluno09@buska.app",
            "99999999909",
            "83988010009",
            "2024009",
            ufcg.id,
        ),
        ("João Victor Leal", "aluno10@buska.app", "10101010110", "83988010010", "2024010", uepb.id),
        (
            "Karen Alves Freitas",
            "aluno11@buska.app",
            "11011011111",
            "83988010011",
            "2024011",
            uepb.id,
        ),
        (
            "Lucas Barbosa Lima",
            "aluno12@buska.app",
            "12012012212",
            "83988010012",
            "2024012",
            uepb.id,
        ),
        (
            "Mariana Vieira Santos",
            "aluno13@buska.app",
            "13013013313",
            "83988010013",
            "2024013",
            ufcg.id,
        ),
        (
            "Nathan Queiroz Brito",
            "aluno14@buska.app",
            "14014014414",
            "83988010014",
            "2024014",
            ufcg.id,
        ),
        (
            "Olivia Pessoa Alencar",
            "aluno15@buska.app",
            "15015015515",
            "83988010015",
            "2024015",
            ufcg.id,
        ),
        (
            "Pedro Cavalcanti Luz",
            "aluno16@buska.app",
            "16016016616",
            "83988010016",
            "2024016",
            uepb.id,
        ),
        (
            "Quinn Ribeiro Maia",
            "aluno17@buska.app",
            "17017017717",
            "83988010017",
            "2024017",
            uepb.id,
        ),
        (
            "Renata Castro Farias",
            "aluno18@buska.app",
            "18018018818",
            "83988010018",
            "2024018",
            ufcg.id,
        ),
        (
            "Samuel Lopes Correia",
            "aluno19@buska.app",
            "19019019919",
            "83988010019",
            "2024019",
            ufcg.id,
        ),
        (
            "Tânia Moura Henrique",
            "aluno20@buska.app",
            "20020020020",
            "83988010020",
            "2024020",
            uepb.id,
        ),
    ]

    # Realistic adult birth years: 1998–2005 (ages 20–27 in 2026)
    adult_dobs = [
        date(2001, 3, 12),
        date(2000, 7, 25),
        date(2002, 11, 4),
        date(1999, 1, 18),
        date(2003, 6, 30),
        date(2001, 9, 14),
        date(2000, 4, 22),
        date(2002, 8, 9),
        date(2003, 2, 17),
        date(1998, 12, 3),
        date(2004, 5, 28),
        date(2001, 10, 7),
        date(2000, 3, 19),
        date(2002, 7, 11),
        date(1999, 8, 24),
        date(2003, 1, 5),
        date(2001, 6, 16),
        date(2000, 11, 29),
    ]
    # Last 2 are minors (born 2009–2010, ages 15–16 in 2026)
    minor_dobs = [date(2009, 5, 15), date(2010, 2, 8)]
    all_dobs = adult_dobs + minor_dobs

    alunos = []
    for i, (nome, email, cpf, tel, mat, inst_id) in enumerate(nomes):
        # Last 2 alunos are minors waiting for gestor approval (guardian already consented)
        is_minor_demo = i >= 18
        status = UserStatus.PENDING_APPROVAL if is_minor_demo else UserStatus.ACTIVE
        nome_responsavel = f"José {nome.split()[0]}" if is_minor_demo else None
        cpf_responsavel = f"9{cpf[1:]}" if is_minor_demo else None
        email_responsavel = f"resp{i+1}@buska.app" if is_minor_demo else None
        guardian_consented_at = datetime.now(UTC) if is_minor_demo else None

        a = _aluno(
            pref.id,
            nome,
            email,
            cpf,
            tel,
            pw,
            mat,
            inst_id,
            casas[i].id,
            status=status,
            nome_responsavel=nome_responsavel,
            cpf_responsavel=cpf_responsavel,
            email_responsavel=email_responsavel,
            guardian_consented_at=guardian_consented_at,
            data_nascimento=all_dobs[i],
        )
        alunos.append(a)

    db.session.flush()

    # ── 9. Inscrições nas rotas ───────────────────────────────────────────────
    # Rota A (Galante): alunos 0-4 (5 alunos)
    # Rota B (Bodocongó): alunos 5-9
    # Rota C (Queimadas): alunos 10-14
    # Rota D (José Pinheiro): alunos 15-17 (18-19 pending, no enrollments)
    inscricoes = [
        (rota_a, alunos[:5]),
        (rota_b, alunos[5:10]),
        (rota_c, alunos[10:15]),
        (rota_d, alunos[15:18]),
    ]
    for rota, grupo in inscricoes:
        for aluno in grupo:
            ra = RotaAluno(rota_id=rota.id, aluno_id=aluno.id)
            db.session.add(ra)

    db.session.flush()

    # ── 10. Viagens ───────────────────────────────────────────────────────────
    print("Creating trips...")

    # Helper: datetime at HH:MM on a given date
    def _dt(d, h, m):
        return datetime(d.year, d.month, d.day, h, m, tzinfo=UTC)

    # FINALIZADAS (últimos 7 dias)
    viagens_fin = []
    for delta in range(1, 5):
        d = today - timedelta(days=delta)
        h_inicio = _dt(d, 5, 30)
        h_fim = _dt(d, 7, 45)
        v = _viagem(hor_a_ida, mot1, bus1, d, StatusViagem.FINALIZADA, h_inicio, h_fim)
        viagens_fin.append(v)

    db.session.flush()

    # Confirmar alunos em viagens finalizadas
    pontos_embarque_a = [p_mirande, p_catole, p_terminal, p_mirande, p_catole]
    for v in viagens_fin[:2]:
        for aluno, ponto in zip(alunos[:5], pontos_embarque_a, strict=False):
            _confirmar(v, aluno, ponto, confirmado=True)

    # Viagem finalizada de rota B (3 dias atrás)
    d3 = today - timedelta(days=3)
    vb_fin = _viagem(
        hor_b_ida, mot2, bus2, d3, StatusViagem.FINALIZADA, _dt(d3, 6, 0), _dt(d3, 7, 30)
    )
    db.session.flush()
    for aluno, ponto in zip(alunos[5:10], [p_bodocongo, p_liberdade] * 3, strict=False):
        _confirmar(vb_fin, aluno, ponto)

    # CANCELADAS
    vc1 = _viagem(hor_c_ida, mot3, bus3, today - timedelta(days=2), StatusViagem.CANCELADA)
    _viagem(hor_d_tarde, mot1, bus4, today - timedelta(days=1), StatusViagem.CANCELADA)

    # EM_ANDAMENTO (hoje)
    v_em1 = _viagem(
        hor_a_ida, mot1, bus1, today, StatusViagem.EM_ANDAMENTO, _dt(today, 5, 30), None
    )
    v_em2 = _viagem(hor_b_ida, mot2, bus2, today, StatusViagem.EM_ANDAMENTO, _dt(today, 6, 0), None)

    db.session.flush()

    # Confirmações em andamento
    for aluno, ponto in zip(alunos[:5], pontos_embarque_a, strict=False):
        _confirmar(v_em1, aluno, ponto)
    for aluno, ponto in zip(alunos[5:10], [p_bodocongo, p_liberdade] * 3, strict=False):
        _confirmar(v_em2, aluno, ponto)

    # AGENDADAS (próximos 3 dias)
    viagens_ag = []
    for delta in range(1, 4):
        d = today + timedelta(days=delta)
        va = _viagem(hor_a_ida, mot1, bus1, d, StatusViagem.AGENDADA)
        vb = _viagem(hor_b_ida, mot2, bus2, d, StatusViagem.AGENDADA)
        viagens_ag.extend([va, vb])

    db.session.flush()

    # Confirmar alguns alunos em viagens agendadas
    for v in viagens_ag[:2]:
        for aluno, ponto in zip(alunos[:3], pontos_embarque_a[:3], strict=False):
            _confirmar(v, aluno, ponto)

    # ── 11. Ocorrências ───────────────────────────────────────────────────────
    print("Creating occurrences...")

    _ocorrencia(
        alunos[0].id,
        v_em1.id,
        TipoOcorrencia.SUPERLOTACAO,
        "O ônibus chegou lotado em Galante hoje — não consegui embarcar.",
        StatusOcorrencia.ABERTA,
    )
    _ocorrencia(
        alunos[5].id,
        vb_fin.id,
        TipoOcorrencia.ATRASO,
        "Ônibus chegou 25 minutos atrasado na parada de Bodocongó.",
        StatusOcorrencia.RESOLVIDA,
    )
    _ocorrencia(
        mot3.id,
        vc1.id,
        TipoOcorrencia.OUTRO,
        "Problema mecânico no motor — solicitei guincho. Viagem cancelada.",
        StatusOcorrencia.RESOLVIDA,
    )
    _ocorrencia(
        alunos[10].id,
        None,
        TipoOcorrencia.COMPORTAMENTO,
        "Motorista ignorou parada combinada em Cruz das Armas (semana passada).",
        StatusOcorrencia.ABERTA,
    )

    # ── 12. Notificações ──────────────────────────────────────────────────────
    print("Creating notifications...")

    for aluno in alunos[:5]:
        _notificacao(
            aluno.id,
            "🚌 Viagem Iniciada!",
            "Carlos iniciou a rota Galante → UFCG. Acompanhe no mapa!",
            lida=True,
            dias_atras=1,
        )

    for aluno in alunos[5:10]:
        _notificacao(
            aluno.id,
            "⏰ Lembrete de Viagem",
            "Sua viagem pela rota Bodocongó → UEPB começa amanhã às 06:00.",
            lida=False,
            dias_atras=0,
        )

    for aluno in alunos[:3]:
        _notificacao(
            aluno.id,
            "⚠️ Aviso do Motorista",
            "Pequeno atraso previsto hoje — trânsito na Av. Manoel Tavares.",
            lida=False,
            dias_atras=0,
        )

    _notificacao(
        gestor.id,
        "📋 Nova Ocorrência Registrada",
        "O aluno Ana Carla reportou superlotação na rota Galante → UFCG.",
        lida=False,
        dias_atras=0,
    )
    _notificacao(
        gestor.id,
        "✅ Ocorrência Resolvida",
        "A ocorrência de atraso na rota Bodocongó → UEPB foi marcada como resolvida.",
        lida=True,
        dias_atras=3,
    )

    db.session.commit()

    print("\n" + "=" * 50)
    print("SUCCESS! Demo database populated.")
    print("=" * 50)
    print(f"\nTest credentials (senha: {TEST_PASSWORD}):")
    print("  Gestor:    admin@buska.app")
    print("  Motorista: carlos@buska.app  (Galante → UFCG)")
    print("  Motorista: silvio@buska.app  (Bodocongó → UEPB)")
    print("  Motorista: rosangela@buska.app (Queimadas → UFCG)")
    print("  Aluno:     aluno01@buska.app … aluno20@buska.app")
    print("\nRoutes:")
    print("  A – Galante → UFCG       (05:30, 5 alunos, Carlos + Sprinter)")
    print("  B – Bodocongó → UEPB     (06:00, 5 alunos, Silvio + Volare)")
    print("  C – Queimadas → UFCG     (05:00, 5 alunos, Rosângela + VW)")
    print("  D – José Pinheiro → UFCG/UEPB (12:30, 3 alunos, Carlos + Marcopolo)")
    print("\nTrip statuses today:")
    print("  EM_ANDAMENTO: rota A, rota B")
    print("  AGENDADA: rotas A + B nos próximos 3 dias")
    print("  FINALIZADA: rota A (×4), rota B (×1) nos últimos dias")
    print("  CANCELADA: rota C, rota D (ontem/anteontem)")
    print("\nMinors (PENDING_APPROVAL):")
    print("  aluno19@buska.app — Samuel Lopes Correia")
    print("  aluno20@buska.app — Tânia Moura Henrique\n")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────


def seed_database() -> None:
    with app.app_context():
        print("\n" + "=" * 50)
        print("BusKa Database Seed")
        print("=" * 50)

        try:
            seed_catalog_from_csv()
            seed_demo_data()
        except Exception as e:
            db.session.rollback()
            print(f"\nError: {e}")
            raise


if __name__ == "__main__":
    seed_database()
