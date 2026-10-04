from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from platform_backend.config import settings
from platform_backend.db.models import Base

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)
    ensure_indexes()


def ensure_indexes() -> None:
    """
    `create_all` builds indexes only when it creates their table, so a database made before an
    index was added never gets it. Create any that are missing. A unique index that existing
    rows violate cannot be built; that is logged, not fatal — the application still checks.
    """
    import logging
    for table in Base.metadata.sorted_tables:
        for index in table.indexes:
            try:
                index.create(bind=engine, checkfirst=True)
            except Exception as exc:  # noqa: BLE001
                logging.getLogger("aurelix.db").warning("could not create index %s: %s", index.name, exc)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
