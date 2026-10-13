"""Load the labeled synthetic corpus through the real ingestion pipeline."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.service import sync_alerts
from app.ingestion.pipeline import ingest_directory
from app.models import RemittanceFile
from app.rag.knowledge import index_all_documents
from app.seed.reference import ensure_knowledge, ensure_synthetic_contracts, ensure_synthetic_submission_events
from app.synthetic.corpus import monthly_history, required_scenarios


def write_synthetic_files(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, text in {**required_scenarios(), **monthly_history()}.items():
        (directory / name).write_text(text, encoding="utf-8")


def seed_demo_corpus(db: Session, settings) -> dict:
    if db.scalar(select(RemittanceFile.id).limit(1)) is not None:
        return {"skipped": True}
    directory = Path(settings.ingest_root) / "synthetic_835"
    write_synthetic_files(directory)
    stats = ingest_directory(db, directory, "mock_central_reach")
    ensure_synthetic_contracts(db)
    ensure_synthetic_submission_events(db)
    ensure_knowledge(db)
    index_all_documents(db, settings)
    db.commit()
    sync_alerts(db, settings)
    return stats
