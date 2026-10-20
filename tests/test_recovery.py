"""DB-backed recovery tests for the transaction webhook service.

These tests use the configured PostgreSQL database and clean up only uniquely
named records. The Celery publish call is deliberately failed for deterministic
dispatch retry coverage; database operations remain real.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from celery.exceptions import Retry

from app.db.models import OutboxEvent, Transaction
from app.db.session import SessionLocal
from app.services import outbox_dispatcher
from app.tasks import transactions as transaction_tasks

OLD_TIME = datetime(2000, 1, 1, tzinfo=timezone.utc)


def create_records(*, claimed_until=None):
    transaction_id = f"recovery-{uuid4().hex}"
    with SessionLocal() as db:
        transaction = Transaction(
            transaction_id=transaction_id,
            source_account=f"src-{uuid4().hex[:12]}",
            destination_account=f"dst-{uuid4().hex[:12]}",
            amount="12.50",
            currency="USD",
            status="PROCESSING",
            created_at=OLD_TIME,
        )
        db.add(transaction)
        db.flush()
        event = OutboxEvent(
            transaction_id=transaction_id,
            event_type="TRANSACTION_RECEIVED",
            status="PENDING",
            attempts=0,
            next_attempt_at=OLD_TIME,
            created_at=OLD_TIME,
            claimed_until=claimed_until,
        )
        db.add(event)
        db.commit()
        event_id = event.id
    return transaction_id, event_id


def read_event(event_id):
    with SessionLocal() as db:
        event = db.get(OutboxEvent, event_id)
        assert event is not None
        return {
            "status": event.status,
            "attempts": event.attempts,
            "next_attempt_at": event.next_attempt_at,
            "last_error": event.last_error,
            "claimed_until": event.claimed_until,
            "dispatched_at": event.dispatched_at,
        }


def read_transaction(transaction_id):
    with SessionLocal() as db:
        transaction = db.scalar(
            __import__("sqlalchemy")
            .select(Transaction)
            .where(Transaction.transaction_id == transaction_id)
        )
        assert transaction is not None
        return transaction.status, transaction.processed_at


def cleanup_records(transaction_id):
    with SessionLocal() as db:
        db.query(OutboxEvent).filter_by(transaction_id=transaction_id).delete()
        db.query(Transaction).filter_by(transaction_id=transaction_id).delete()
        db.commit()


def test_dispatch_failure_schedules_retry_and_releases_claim(monkeypatch):
    transaction_id, event_id = create_records()
    try:

        def fail_publish(*args, **kwargs):
            raise ConnectionError("test broker unavailable")

        monkeypatch.setattr(outbox_dispatcher.celery_app, "send_task", fail_publish)
        assert outbox_dispatcher.dispatch_one_event() is True
        event = read_event(event_id)
        assert event["status"] == "PENDING"
        assert event["attempts"] == 1
        assert "test broker unavailable" in event["last_error"]
        assert event["next_attempt_at"] > datetime.now(timezone.utc)
        assert event["claimed_until"] is None
        assert event["dispatched_at"] is None
    finally:
        cleanup_records(transaction_id)


def test_successful_dispatch_persists_timestamp_and_clears_claim(monkeypatch):
    transaction_id, event_id = create_records()
    try:
        published = []
        monkeypatch.setattr(
            outbox_dispatcher.celery_app,
            "send_task",
            lambda name, args: published.append((name, args)),
        )
        assert outbox_dispatcher.dispatch_one_event() is True
        event = read_event(event_id)
        assert event["status"] == "DISPATCHED"
        assert event["dispatched_at"] is not None
        assert event["claimed_until"] is None
        assert event["attempts"] == 1
        assert published == [
            ("app.tasks.transactions.process_transaction", [transaction_id])
        ]
    finally:
        cleanup_records(transaction_id)


def test_expired_claim_is_eligible_for_dispatch(monkeypatch):
    transaction_id, event_id = create_records(
        claimed_until=datetime.now(timezone.utc) - timedelta(seconds=5)
    )
    try:
        published = []
        monkeypatch.setattr(
            outbox_dispatcher.celery_app,
            "send_task",
            lambda name, args: published.append((name, args)),
        )
        assert outbox_dispatcher.dispatch_one_event() is True
        event = read_event(event_id)
        assert event["status"] == "DISPATCHED"
        assert event["dispatched_at"] is not None
        assert event["claimed_until"] is None
        assert published
    finally:
        cleanup_records(transaction_id)


def test_worker_transient_error_requests_celery_retry(monkeypatch):
    transaction_id, _event_id = create_records()
    try:

        def fail_processing(_seconds):
            raise RuntimeError("simulated transient processing failure")

        retry_calls = []

        def fake_retry(*, exc, countdown):
            retry_calls.append((str(exc), countdown))
            raise Retry("retry requested")

        monkeypatch.setattr(transaction_tasks.time, "sleep", fail_processing)
        monkeypatch.setattr(transaction_tasks.process_transaction, "retry", fake_retry)
        transaction_tasks.process_transaction.push_request(retries=0)
        try:
            with pytest.raises(Retry, match="retry requested"):
                transaction_tasks.process_transaction.run(transaction_id)
        finally:
            transaction_tasks.process_transaction.pop_request()

        assert retry_calls == [("simulated transient processing failure", 5)]
        status, processed_at = read_transaction(transaction_id)
        assert status == "PROCESSING"
        assert processed_at is None
    finally:
        cleanup_records(transaction_id)


def test_worker_retry_exhaustion_persists_failed_status(monkeypatch):
    transaction_id, _event_id = create_records()
    try:

        def fail_processing(_seconds):
            raise RuntimeError("simulated permanent processing failure")

        monkeypatch.setattr(transaction_tasks.time, "sleep", fail_processing)
        transaction_tasks.process_transaction.push_request(retries=3)
        try:
            result = transaction_tasks.process_transaction.run(transaction_id)
        finally:
            transaction_tasks.process_transaction.pop_request()

        status, processed_at = read_transaction(transaction_id)
        assert result["status"] == "FAILED"
        assert status == "FAILED"
        assert processed_at is not None
    finally:
        cleanup_records(transaction_id)
