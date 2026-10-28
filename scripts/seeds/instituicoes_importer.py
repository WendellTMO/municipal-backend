import csv
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert

from app.models.base import db
from app.models.enum import TipoInstituicao
from app.models.geo import Instituicao
from app.models.prefeitura import Prefeitura

BATCH_SIZE = 10


def _open_csv(path: str | Path):
    path = Path(path)

    encodings = ("utf-8-sig", "utf-8", "latin-1")
    last_error = None

    for encoding in encodings:
        try:
            file = path.open("r", encoding=encoding, newline="")
            file.read(1)
            file.seek(0)
            return file
        except UnicodeDecodeError as exc:
            last_error = exc

    if last_error:
        raise last_error

    return path.open("r", encoding="utf-8", newline="")


def _clean(value: str | None) -> str | None:
    if value is None:
        return None

    value = str(value).strip()
    return value or None


def _normalize_key(value: str) -> str:
    return value.strip().lower()


def _normalize_ibge_code(value: str | None) -> str | None:
    cleaned = _clean(value)
    if not cleaned:
        return None

    digits_only = "".join(ch for ch in cleaned if ch.isdigit())
    if not digits_only:
        return None

    return str(int(digits_only))


def _load_prefeitura_indexes():
    prefeituras = Prefeitura.query.all()

    by_ibge: dict[str, str] = {}
    by_name_uf: dict[tuple[str, str], str] = {}

    for prefeitura in prefeituras:
        normalized_ibge = _normalize_ibge_code(prefeitura.codigo_ibge)
        if normalized_ibge:
            by_ibge[normalized_ibge] = prefeitura.id

        by_name_uf[(_normalize_key(prefeitura.nome), prefeitura.estado.upper())] = prefeitura.id

    return by_ibge, by_name_uf


def _upsert_batch(rows: list[dict]) -> None:
    if not rows:
        return

    stmt = insert(Instituicao).values(rows)

    stmt = stmt.on_conflict_do_update(
        constraint="uq_instituicao_fonte_codigo_externo",
        set_={
            "nome": stmt.excluded.nome,
            "sigla": stmt.excluded.sigla,
            "tipo": stmt.excluded.tipo,
            "uf": stmt.excluded.uf,
            "prefeitura_id": stmt.excluded.prefeitura_id,
            "situacao": stmt.excluded.situacao,
            "categoria_administrativa": stmt.excluded.categoria_administrativa,
            "organizacao_academica": stmt.excluded.organizacao_academica,
        },
    )

    db.session.execute(stmt)
    db.session.commit()


def _map_ies_row(
    row: dict[str, str],
    prefeituras_by_ibge: dict[str, str],
    prefeituras_by_name_uf: dict[tuple[str, str], str],
) -> dict | None:
    codigo_externo = _clean(row.get("CODIGO_DA_IES"))
    nome = _clean(row.get("NOME_DA_IES"))
    sigla = _clean(row.get("SIGLA"))
    uf = _clean(row.get("UF"))
    municipio = _clean(row.get("MUNICIPIO"))
    categoria = _clean(row.get("CATEGORIA_DA_IES"))
    organizacao = _clean(row.get("ORGANIZACAO_ACADEMICA"))
    situacao = _clean(row.get("SITUACAO_IES"))
    codigo_municipio_ibge = _normalize_ibge_code(row.get("CODIGO_MUNICIPIO_IBGE"))

    if not codigo_externo or not nome or not categoria:
        return None

    prefeitura_id = None

    if codigo_municipio_ibge:
        prefeitura_id = prefeituras_by_ibge.get(codigo_municipio_ibge)

    if not prefeitura_id and municipio and uf:
        prefeitura_id = prefeituras_by_name_uf.get((_normalize_key(municipio), uf.upper()))

    if not prefeitura_id or not uf:
        return None

    categoria_lower = categoria.lower()
    organizacao_lower = (organizacao or "").lower()

    if "instituto federal" in organizacao_lower:
        tipo = TipoInstituicao.INSTITUTO_FEDERAL
    elif categoria_lower == "pública":
        tipo = TipoInstituicao.UNIVERSIDADE_PUBLICA
    else:
        tipo = TipoInstituicao.UNIVERSIDADE_PRIVADA

    return {
        "fonte": "EMEC",
        "codigo_externo": codigo_externo,
        "nome": nome,
        "sigla": sigla,
        "tipo": tipo,
        "uf": uf,
        "prefeitura_id": prefeitura_id,
        "situacao": situacao,
        "categoria_administrativa": categoria,
        "organizacao_academica": organizacao,
        "ponto_id": None,
    }


def _map_escola_row(
    row: dict[str, str],
    prefeituras_by_name_uf: dict[tuple[str, str], str],
) -> dict | None:
    codigo_externo = _clean(row.get("Código INEP"))
    nome = _clean(row.get("Escola"))
    uf = _clean(row.get("UF"))
    municipio = _clean(row.get("Município"))
    categoria = _clean(row.get("Categoria Administrativa"))

    if not codigo_externo or not nome or not uf or not municipio or not categoria:
        return None

    prefeitura_id = prefeituras_by_name_uf.get((_normalize_key(municipio), uf.upper()))
    if not prefeitura_id:
        return None

    categoria_lower = categoria.lower()

    if categoria_lower == "pública":
        tipo = TipoInstituicao.ESCOLA_PUBLICA
    elif categoria_lower == "privada":
        tipo = TipoInstituicao.ESCOLA_PRIVADA
    else:
        tipo = TipoInstituicao.ESCOLA_COMUNITARIA

    return {
        "fonte": "INEP",
        "codigo_externo": codigo_externo,
        "nome": nome,
        "sigla": None,
        "tipo": tipo,
        "uf": uf,
        "prefeitura_id": prefeitura_id,
        "situacao": _clean(row.get("Restrição de Atendimento")),
        "categoria_administrativa": categoria,
        "organizacao_academica": None,
        "ponto_id": None,
    }


def import_ies_csv(path: str | Path) -> int:
    total = skipped = 0
    buffer: list[dict] = []
    prefeituras_by_ibge, prefeituras_by_name_uf = _load_prefeitura_indexes()

    with _open_csv(path) as csvfile:
        reader = csv.DictReader(csvfile)

        for row in reader:
            mapped = _map_ies_row(row, prefeituras_by_ibge, prefeituras_by_name_uf)
            if not mapped:
                skipped += 1
                continue

            buffer.append(mapped)

            if len(buffer) >= BATCH_SIZE:
                _upsert_batch(buffer)
                total += len(buffer)
                buffer = []

    if buffer:
        _upsert_batch(buffer)
        total += len(buffer)

    print(f"[IES] skipped rows: {skipped}")
    return total


def import_escolas_csv(path: str | Path) -> int:
    total = 0
    buffer: list[dict] = []
    _, prefeituras_by_name_uf = _load_prefeitura_indexes()

    with _open_csv(path) as csvfile:
        reader = csv.DictReader(csvfile)

        for row in reader:
            mapped = _map_escola_row(row, prefeituras_by_name_uf)
            if not mapped:
                continue

            buffer.append(mapped)

            if len(buffer) >= BATCH_SIZE:
                _upsert_batch(buffer)
                total += len(buffer)
                buffer = []

    if buffer:
        _upsert_batch(buffer)
        total += len(buffer)

    return total
