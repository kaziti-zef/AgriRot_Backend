"""Moteur SQLAlchemy et session par requête."""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app import config
from app.db.models import Base

engine = None
SessionLocal = None


def init(url: str | None = None):
    global engine, SessionLocal
    url = url or config.DATABASE_URL
    # Railway, Render, Neon… fournissent « postgres:// » : on choisit explicitement le pilote psycopg 3
    for prefixe in ("postgres://", "postgresql://"):
        if url.startswith(prefixe):
            url = "postgresql+psycopg://" + url[len(prefixe):]
    args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=args, pool_pre_ping=True)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _fk(conn, _):
            conn.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    _completer_colonnes()
    SessionLocal = sessionmaker(engine, expire_on_commit=False)


def _completer_colonnes():
    """Mini-migration : ajoute les colonnes apparues après la création d'une base existante (create_all ne le fait pas)."""
    from sqlalchemy import inspect, text
    ins = inspect(engine)
    ajouts = {"saved_strategies": {"monitoring_active": "BOOLEAN NOT NULL DEFAULT FALSE", "monitoring_state": "JSON"}}
    with engine.begin() as cx:
        for table, colonnes in ajouts.items():
            presentes = {c["name"] for c in ins.get_columns(table)}
            for nom, ddl in colonnes.items():
                if nom not in presentes:
                    cx.execute(text(f"ALTER TABLE {table} ADD COLUMN {nom} {ddl}"))


def get_db():
    if SessionLocal is None:
        init()
    db: Session = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
