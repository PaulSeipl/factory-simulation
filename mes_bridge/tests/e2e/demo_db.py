"""The showcase database of `mes_bridge/DEMO.md`: create, fill, drop. Never the dev database.

Runs in the MES backend's environment, from `backend/`:

    uv run python <this file> setup [name]     # default name: mes_demo
    uv run python <this file> drop [name]

`setup` (re)creates the database `name` (it must start with `mes_demo`), migrates it (`alembic upgrade head`), runs
`app/initial_data.py` (admin / admin and five workers, password `fidentis_<user_name>`), creates the `scheduler`
service account with a generated password, and seeds the showcase orders (`mes_driver.py demo`). The generated
secrets (scheduler password, events token) go to `<temp>/mes_demo_secrets.ps1`, to dot-source in the MES and
bridge terminals; they are never printed in full.
"""

import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg

from app.core.config import settings

HERE = Path(__file__).resolve().parent
SECRETS = Path(tempfile.gettempdir()) / "mes_demo_secrets.ps1"


def _admin():
    return (
        f"host={settings.HOST_POSTGRESQL} user={settings.POSTGRESQL_ADMIN_USER} "
        f"password={settings.POSTGRESQL_ADMIN_PASS} dbname=postgres"
    )


def _sql(q: str) -> None:
    with psycopg.connect(_admin(), autocommit=True) as c:
        c.execute(q)


def _run(*args: str, env: dict[str, str]) -> None:
    print("$", *args[1:] if args[0] == sys.executable else args)
    subprocess.run(list(args), env=env, check=True)


def setup(name: str) -> None:
    _sql(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
    _sql(f"CREATE DATABASE {name}")
    password, token = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    env = {**os.environ, "POSTGRESQL_DB_NAME": name, "PYTHONPATH": os.getcwd()}
    _run(sys.executable, "-m", "alembic", "upgrade", "head", env=env)
    _run(sys.executable, "app/initial_data.py", env=env)
    subprocess.run(
        [sys.executable, "-m", "scripts.create_user", "--username", settings.SCHEDULER_USERNAME,
         "--password", password, "--allow-no-worker"],
        env=env, check=True,
    )  # fmt: skip
    _run(sys.executable, str(HERE / "mes_driver.py"), "demo", env=env)
    SECRETS.write_text(
        f'$env:POSTGRESQL_DB_NAME = "{name}"\n'
        f'$env:MES_SCHEDULER_PASSWORD = "{password}"\n'
        f'$env:MES_EVENTS_TOKEN = "{token}"\n'
        f'$env:SCHEDULER_EVENTS_TOKEN = "{token}"\n'
        '$env:SCHEDULER_URL = "http://127.0.0.1:8766"\n',
        encoding="utf-8",
    )
    print(f"database {name} ready; secrets in {SECRETS} (dot-source it: . '{SECRETS}')")


def drop(name: str) -> None:
    _sql(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
    SECRETS.unlink(missing_ok=True)
    print(f"dropped {name}")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    name = sys.argv[2] if len(sys.argv) > 2 else "mes_demo"
    if not name.startswith("mes_demo"):
        sys.exit(f"refused: {name!r} is not a demo database (the name must start with mes_demo)")
    if command == "setup":
        setup(name)
    elif command == "drop":
        drop(name)
    else:
        print(__doc__)
        sys.exit(2)
