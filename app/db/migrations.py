from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from app.db.session import SQLALCHEMY_DATABASE_URL
from alembic.runtime.migration import MigrationContext

def run_migrations() -> None:
    BASE_DIR = Path(__file__).resolve().parents[2]
    alembic_ini = BASE_DIR / "alembic.ini"

    cfg = Config(str(alembic_ini))
    cfg.attributes["configure_logger"] = False
    script = ScriptDirectory.from_config(cfg)
    head_rev = script.get_current_head()
    try:
        engine = create_engine(SQLALCHEMY_DATABASE_URL)
        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            current_rev = context.get_current_revision()
        if current_rev == head_rev:
            return
    except Exception as e:
        print(f"Error running migrations: {e}")
        pass
    command.upgrade(cfg, "head")