import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.celery_app import celery_app
from app.db.models import OutboxEvent
from app.db.session import SessionLocal

POLL_INTERVAL_SECONDS = 2
CLAIM_LEASE_SECONDS = 60
MAX_RETRY_DELAY_SECONDS = 300


def dispatch_one_event() -> bool:
    db = SessionLocal()

    try:
        now = datetime.now(timezone.utc)

        # Claim one eligible event inside a short DB transaction.
        event = db.scalar(
            select(OutboxEvent)
            .where(
                OutboxEvent.status == "PENDING",
                OutboxEvent.next_attempt_at <= now,
                (
                    OutboxEvent.claimed_until.is_(None)
                    | (OutboxEvent.claimed_until <= now)
                ),
            )
            .order_by(OutboxEvent.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )

        if event is None:
            db.rollback()
            return False

        event.claimed_until = now + timedelta(seconds=CLAIM_LEASE_SECONDS)
        event.attempts += 1
        event_id = event.id
        transaction_id = event.transaction_id
        event_type = event.event_type

        db.commit()

        # Publish only after the claim is committed.
        try:
            if event_type != "TRANSACTION_RECEIVED":
                raise ValueError(f"Unsupported event type: {event_type}")

            celery_app.send_task(
                "app.tasks.transactions.process_transaction",
                args=[transaction_id],
            )

        except Exception as exc:
            # Release the claim and schedule a retry.
            db.rollback()
            event = db.get(OutboxEvent, event_id)

            if event is not None and event.status == "PENDING":
                delay = min(
                    2 ** min(event.attempts, 8),
                    MAX_RETRY_DELAY_SECONDS,
                )
                event.last_error = str(exc)[:2000]
                event.next_attempt_at = datetime.now(timezone.utc) + timedelta(
                    seconds=delay
                )
                event.claimed_until = None
                db.commit()

            print(f"Outbox publish failed for event {event_id}: {exc}")
            return True

        # Mark as dispatched after successful publication.
        event = db.get(OutboxEvent, event_id)

        if event is not None and event.status == "PENDING":
            event.status = "DISPATCHED"
            event.dispatched_at = datetime.now(timezone.utc)
            event.last_error = None
            event.claimed_until = None
            db.commit()

        print(f"Dispatched event {event_id} " f"for transaction {transaction_id}")
        return True

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def run_dispatcher() -> None:
    print("Outbox dispatcher started.")

    while True:
        try:
            found_event = dispatch_one_event()

            if not found_event:
                time.sleep(POLL_INTERVAL_SECONDS)

        except Exception as exc:
            print(f"Outbox dispatcher error: {exc}")
            time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    run_dispatcher()
