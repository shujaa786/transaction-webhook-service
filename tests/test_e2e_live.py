"""
Live end-to-end tests for Transaction Webhook Service.

These tests use the REAL running API, PostgreSQL, Redis, outbox dispatcher,
and Celery worker. They do not mock the database or queue.

Prerequisites (start these in separate terminals from the project root):
  1) API:        python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
  2) Dispatcher: python -m app.services.outbox_dispatcher
  3) Worker:     celery -A app.celery_app:celery_app worker --pool=solo --loglevel=INFO
  4) PostgreSQL and Redis from docker compose

Run:
  set E2E_API_URL=http://127.0.0.1:8000
  python -m pytest -v -s tests/test_e2e_live.py

The successful-processing test waits up to 50 seconds because the assignment
requires an actual 30-second worker delay.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from uuid import uuid4

import httpx
import pytest
from redis import Redis
from sqlalchemy import delete, func, select

from app.celery_app import celery_app
from app.core.config import settings
from app.db.models import OutboxEvent, Transaction
from app.db.session import SessionLocal
from app.services.outbox_dispatcher import POLL_INTERVAL_SECONDS

API_URL = os.getenv("E2E_API_URL", "http://127.0.0.1:8000").rstrip("/")
HTTP_TIMEOUT_SECONDS = 3.0
DISPATCH_TIMEOUT_SECONDS = 20.0
PROCESSING_TIMEOUT_SECONDS = 50.0


def iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None, f"Timestamp must include timezone: {value}"
    return parsed


@pytest.fixture(scope="session")
def live_client():
    with httpx.Client(base_url=API_URL, timeout=HTTP_TIMEOUT_SECONDS) as client:
        try:
            response = client.get("/")
        except httpx.HTTPError as exc:
            pytest.fail(
                f"Real API is not reachable at {API_URL}: {exc}. "
                "Start uvicorn in a separate terminal."
            )
        assert response.status_code == 200, response.text
        yield client


@pytest.fixture(scope="session", autouse=True)
def verify_infrastructure():
    # Actual Redis connectivity, not a mocked broker.
    redis_url = settings.redis_url
    try:
        redis_client = Redis.from_url(redis_url, socket_connect_timeout=2)
        assert redis_client.ping() is True
    except Exception as exc:
        pytest.fail(f"Redis is not reachable at configured REDIS_URL: {exc}")

    # Require a live Celery worker to answer a real broker control ping.
    try:
        replies = celery_app.control.inspect(timeout=3).ping() or {}
    except Exception as exc:
        pytest.fail(f"Could not inspect Celery workers through Redis: {exc}")
    assert replies, (
        "No Celery worker replied to ping. Start the worker with "
        "'celery -A app.celery_app:celery_app worker --pool=solo --loglevel=INFO'."
    )

    # Confirm PostgreSQL accepts a real SQL query.
    with SessionLocal() as db:
        db.execute(select(1)).scalar_one()


@pytest.fixture
def transaction_payload():
    transaction_id = f"e2e-{uuid4().hex}"
    return {
        "transaction_id": transaction_id,
        "source_account": f"source-{uuid4().hex[:10]}",
        "destination_account": f"destination-{uuid4().hex[:10]}",
        "amount": "12.50",
        "currency": "USD",
    }


@pytest.fixture
def cleanup_transaction():
    created_ids: list[str] = []
    yield created_ids
    # Remove only records created by this test; never truncate shared tables.
    with SessionLocal() as db:
        for transaction_id in created_ids:
            db.execute(
                delete(OutboxEvent).where(OutboxEvent.transaction_id == transaction_id)
            )
            db.execute(
                delete(Transaction).where(Transaction.transaction_id == transaction_id)
            )
        db.commit()


def get_db_records(transaction_id: str):
    with SessionLocal() as db:
        transaction = db.scalar(
            select(Transaction).where(Transaction.transaction_id == transaction_id)
        )
        event = db.scalar(
            select(OutboxEvent).where(
                OutboxEvent.transaction_id == transaction_id,
                OutboxEvent.event_type == "TRANSACTION_RECEIVED",
            )
        )
        transaction_count = db.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.transaction_id == transaction_id)
        )
        event_count = db.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.transaction_id == transaction_id)
        )
        # Return scalar snapshots, not detached ORM instances.
        transaction_data = None
        if transaction is not None:
            transaction_data = {
                "transaction_id": transaction.transaction_id,
                "source_account": transaction.source_account,
                "destination_account": transaction.destination_account,
                "amount": str(transaction.amount),
                "currency": transaction.currency,
                "status": transaction.status,
                "created_at": transaction.created_at,
                "processed_at": transaction.processed_at,
            }
        event_data = None
        if event is not None:
            event_data = {
                "status": event.status,
                "attempts": event.attempts,
                "last_error": event.last_error,
                "dispatched_at": event.dispatched_at,
                "claimed_until": event.claimed_until,
            }
        return transaction_data, event_data, transaction_count, event_count


def wait_for(predicate, timeout: float, interval: float = 0.5):
    deadline = time.monotonic() + timeout
    last_value = None
    while time.monotonic() < deadline:
        last_value = predicate()
        if last_value:
            return last_value
        time.sleep(interval)
    return last_value


def test_live_health_contract(live_client):
    response = live_client.get("/")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "HEALTHY"
    assert iso_datetime(body["current_time"])


def test_real_post_get_duplicate_dispatch_and_worker_flow(
    live_client, transaction_payload, cleanup_transaction
):
    transaction_id = transaction_payload["transaction_id"]
    started = time.monotonic()

    # Real HTTP request to the running API.
    post_response = live_client.post(
        "/v1/webhooks/transactions", json=transaction_payload
    )
    elapsed_ms = (time.monotonic() - started) * 1000
    assert post_response.status_code == 202, post_response.text
    assert elapsed_ms < 500, f"POST took {elapsed_ms:.1f}ms (requirement: <500ms)"
    cleanup_transaction.append(transaction_id)

    transaction, event, transaction_count, event_count = get_db_records(transaction_id)
    assert transaction is not None, "POST returned but transaction was not persisted"
    assert event is not None, "POST returned but durable outbox event was not persisted"
    assert transaction_count == 1
    assert event_count == 1
    assert transaction["status"] == "PROCESSING"
    assert transaction["processed_at"] is None
    assert transaction["source_account"] == transaction_payload["source_account"]
    assert (
        transaction["destination_account"] == transaction_payload["destination_account"]
    )
    assert transaction["amount"] == transaction_payload["amount"]
    assert transaction["currency"] == transaction_payload["currency"]
    assert transaction["created_at"] is not None

    # Duplicate delivery must be acknowledged but must not create another
    # transaction or another outbox event.
    duplicate_response = live_client.post(
        "/v1/webhooks/transactions", json=transaction_payload
    )
    assert duplicate_response.status_code == 202, duplicate_response.text
    _, _, transaction_count, event_count = get_db_records(transaction_id)
    assert transaction_count == 1, f"Duplicate created {transaction_count} transactions"
    assert event_count == 1, f"Duplicate created {event_count} outbox events"

    # The independently running dispatcher must publish this event. Checking
    # persisted dispatched_at also catches the previously observed timestamp bug.
    def dispatched_snapshot():
        _transaction, event_snapshot, _transaction_count, _event_count = get_db_records(
            transaction_id
        )
        if (
            event_snapshot is not None
            and event_snapshot["status"] == "DISPATCHED"
            and event_snapshot["dispatched_at"] is not None
        ):
            return event_snapshot
        return None

    dispatched = wait_for(
        dispatched_snapshot,
        timeout=DISPATCH_TIMEOUT_SECONDS,
        interval=POLL_INTERVAL_SECONDS / 2,
    )
    assert dispatched is not None, (
        "Outbox event was not persisted as DISPATCHED with dispatched_at. "
        "Check the running dispatcher logs and its DB commit."
    )
    assert dispatched["claimed_until"] is None
    assert dispatched["attempts"] >= 1

    # Real worker must finish the real task after its 30-second delay.
    def final_transaction_snapshot():
        transaction_snapshot, _event, _transaction_count, _event_count = get_db_records(
            transaction_id
        )
        if transaction_snapshot is not None and transaction_snapshot["status"] in {
            "PROCESSED",
            "FAILED",
        }:
            return transaction_snapshot
        return None

    final_transaction = wait_for(
        final_transaction_snapshot,
        timeout=PROCESSING_TIMEOUT_SECONDS,
        interval=0.5,
    )
    assert (
        final_transaction is not None
    ), "Worker did not finish within timeout. Check Celery worker logs."
    assert final_transaction["status"] == "PROCESSED"
    assert final_transaction["processed_at"] is not None
    assert final_transaction["processed_at"] >= final_transaction["created_at"]

    # Verify the public GET endpoint reflects the persisted final DB state.
    get_response = live_client.get(f"/v1/transactions/{transaction_id}")
    assert get_response.status_code == 200, get_response.text
    body = get_response.json()
    required_fields = {
        "transaction_id",
        "source_account",
        "destination_account",
        "amount",
        "currency",
        "status",
        "created_at",
        "processed_at",
    }
    assert required_fields.issubset(
        body.keys()
    ), f"GET response missing fields: {required_fields - body.keys()}"
    assert body["transaction_id"] == transaction_id
    assert body["source_account"] == transaction_payload["source_account"]
    assert body["destination_account"] == transaction_payload["destination_account"]
    assert body["amount"] == transaction_payload["amount"]
    assert body["currency"] == transaction_payload["currency"]
    assert body["status"] == "PROCESSED"
    assert iso_datetime(body["created_at"])
    assert iso_datetime(body["processed_at"])


def test_real_api_validation_rejects_invalid_payload(live_client):
    payload = {
        "transaction_id": f"e2e-invalid-{uuid4().hex}",
        "source_account": "same-account",
        "destination_account": "same-account",
        "amount": "12.50",
        "currency": "USD",
    }
    response = live_client.post("/v1/webhooks/transactions", json=payload)
    assert response.status_code == 422, response.text


def test_real_api_returns_404_for_unknown_transaction(live_client):
    response = live_client.get(f"/v1/transactions/not-found-{uuid4().hex}")
    assert response.status_code == 404, response.text
