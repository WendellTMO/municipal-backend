import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from gerar_app_version import montar_manifesto  # noqa: E402


def test_manifesto_completo():
    agora = datetime(2026, 10, 28, 12, 0, 5, tzinfo=UTC)
    m = montar_manifesto(
        29000000,
        "1.2.0-beta",
        "https://buska.lsd.ufcg.edu.br/v1",
        "abc123",
        'Correção "X"| Melhoria Y |',
        5,
        agora,
    )
    assert m == {
        "versionCode": 29000000,
        "versionName": "1.2.0-beta",
        "apkUrl": "https://buska.lsd.ufcg.edu.br/buska.apk",
        "sha256": "abc123",
        "notas": ['Correção "X"', "Melhoria Y"],
        "minVersionCode": 5,
        "publicadoEm": "2026-10-28T12:00:05Z",
    }
    json.loads(json.dumps(m))
