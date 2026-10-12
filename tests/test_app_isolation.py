"""feat-076: importing the web app must not touch the user's real ./data.

Regression guard for a data-safety bug: `memoria/web/app.py` used to end with
`app = create_app()`, so merely importing the module built a real ChromaStore at
`./data/chroma` and write-opened the live sqlite files. Every web test imports
this module, so the "100% offline" suite was writing to the user's actual data
directory — and on Windows that surfaced as real file mtimes changing.

The check is behavioral, not structural: import the module in a subprocess with a
tripwire on the two store constructors and assert neither fired.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import textwrap

TRIPWIRE = textwrap.dedent(
    """
    import json
    import sys
    sys.path.insert(0, "src")

    opened = []

    import chromadb
    _pc = chromadb.PersistentClient
    def _patched(*a, **kw):
        opened.append(["chroma", str(kw.get("path", a[0] if a else ""))])
        return _pc(*a, **kw)
    chromadb.PersistentClient = _patched

    import sqlite3
    _sc = sqlite3.connect
    def _patched_sqlite(database, *a, **kw):
        opened.append(["sqlite", str(database)])
        return _sc(database, *a, **kw)
    sqlite3.connect = _patched_sqlite

    import memoria.web.app  # noqa: F401  — the import itself is the test

    real = [o for o in opened if "Temp" not in o[1] and "pytest-of-" not in o[1]]
    print("OPENED:" + json.dumps(real))
    """
)


def test_importing_web_app_does_not_open_real_data_stores():
    result = subprocess.run(
        [sys.executable, "-c", TRIPWIRE],
        capture_output=True,
        text=True,
        cwd=str(pathlib.Path(__file__).resolve().parents[1]),
    )
    assert result.returncode == 0, result.stderr
    line = next(l for l in result.stdout.splitlines() if l.startswith("OPENED:"))
    opened = json.loads(line[len("OPENED:") :])
    assert opened == [], (
        "importing memoria.web.app opened real data stores: "
        f"{opened} — the module must not build the app at import time (feat-076)"
    )


def test_web_app_exposes_a_factory_for_uvicorn():
    """Production launches via the factory; there must be no import-time singleton."""
    import memoria.web.app as web_app

    assert not hasattr(web_app, "app"), (
        "module-level `app = create_app()` is back — it re-introduces the real-data "
        "leak on every import (feat-076)"
    )
    assert callable(web_app.create_app)
