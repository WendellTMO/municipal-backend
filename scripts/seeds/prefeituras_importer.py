import csv
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert

from app.models.base import db
from app.models.prefeitura import Prefeitura

BATCH_SIZE = 1000


def _open_csv(path: str | Path):
    path = Path(path)

    encodings = ("utf-8-sig", "latin-1", "utf-8")
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


def _upsert_batch(rows: list[dict]) -> None:
    if not rows:
        return

    stmt = insert(Prefeitura).values(rows)

    stmt = stmt.on_conflict_do_update(
        index_elements=["codigo_ibge"],
        set_={
            "nome": stmt.excluded.nome,
            "estado": stmt.excluded.estado,
            "ativo": stmt.excluded.ativo,
        },
    )

    db.session.execute(stmt)
    db.session.commit()


def import_prefeituras_csv(path: str | Path) -> int:
    total = 0
    buffer: list[dict] = []

    with _open_csv(path) as csvfile:
        reader = csv.DictReader(csvfile, delimiter=";")

        for row in reader:
            codigo_ibge = _clean(row.get("CÓDIGO DO MUNICÍPIO - IBGE")) or _clean(
                row.get("C�DIGO DO MUNIC�PIO - IBGE")
            )
            nome = _clean(row.get("MUNICÍPIO - IBGE")) or _clean(row.get("MUNIC�PIO - IBGE"))
            estado = _clean(row.get("UF"))

            if not codigo_ibge or not nome or not estado:
                continue

            buffer.append(
                {
                    "codigo_ibge": codigo_ibge,
                    "nome": nome,
                    "estado": estado,
                    "ativo": True,
                }
            )

            if len(buffer) >= BATCH_SIZE:
                _upsert_batch(buffer)
                total += len(buffer)
                buffer = []

    if buffer:
        _upsert_batch(buffer)
        total += len(buffer)

    return total
