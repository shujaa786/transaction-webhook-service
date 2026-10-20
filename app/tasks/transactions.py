import time
from datetime import datetime, timezone

from celery import shared_task
from sqlalchemy import select

from app.db.models import Transaction
from app.db.session import SessionLocal


@shared_task(
    name="app.tasks.transactions.process_transaction",
    bind=True,
    max_retries=3,
)
def process_transaction(self, transaction_id: str):
    """Process a transaction once; retry transient failures and persist exhaustion."""
    db = SessionLocal()

    try:
        transaction = db.scalar(
            select(Transaction)
            .where(Transaction.transaction_id == transaction_id)
            .with_for_update()
        )

        if transaction is None:
            return {"transaction_id": transaction_id, "status": "NOT_FOUND"}

        # Duplicate task delivery must not reprocess a terminal transaction.
        if transaction.status != "PROCESSING":
            return {"transaction_id": transaction_id, "status": transaction.status}

        time.sleep(30)

        transaction.status = "PROCESSED"
        transaction.processed_at = datetime.now(timezone.utc)
        db.commit()

        return {"transaction_id": transaction_id, "status": "PROCESSED"}

    except Exception as exc:
        db.rollback()

        # Celery's retry count is zero-based: retries=3 means the retry limit
        # has been reached for this execution. Persist a terminal state rather
        # than leaving the transaction stuck in PROCESSING forever.
        if self.request.retries >= self.max_retries:
            try:
                transaction = db.scalar(
                    select(Transaction)
                    .where(Transaction.transaction_id == transaction_id)
                    .with_for_update()
                )
                if transaction is not None and transaction.status == "PROCESSING":
                    transaction.status = "FAILED"
                    transaction.processed_at = datetime.now(timezone.utc)
                    db.commit()
            except Exception:
                db.rollback()
                raise
            return {"transaction_id": transaction_id, "status": "FAILED"}

        raise self.retry(exc=exc, countdown=5)

    finally:
        db.close()
