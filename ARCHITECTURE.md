## 1. High-Level Architecture

```mermaid
flowchart TB
    Client["Webhook Client"]
    API["FastAPI Application<br/>POST /v1/webhooks/transactions<br/>GET /v1/transactions/{transaction_id}<br/>GET /"]
    DB[("PostgreSQL<br/>transactions<br/>outbox_events")]
    Dispatcher["Outbox Dispatcher<br/>Polls pending events<br/>Claims with row lock + lease"]
    Redis[("Redis<br/>Celery Broker")]
    Worker["Celery Worker<br/>Simulated 30-second processing"]
    Result["Update transaction status<br/>PROCESSED / FAILED"]

    Client -->|"POST webhook"| API
    API -->|"One DB transaction:<br/>insert transaction + outbox event"| DB
    API -->|"202 Accepted"| Client
    Dispatcher -->|"Poll / claim eligible events"| DB
    Dispatcher -->|"Publish task after claim commit"| Redis
    Redis -->|"Deliver task"| Worker
    Worker -->|"Read transaction"| DB
    Worker -->|"Persist status + processed_at"| Result
    Result --> DB
```

## 2. Webhook Ingestion Sequence

```mermaid
sequenceDiagram
    autonumber
    participant C as Webhook Client
    participant A as FastAPI
    participant P as PostgreSQL
    participant D as Outbox Dispatcher
    participant R as Redis
    participant W as Celery Worker

    C->>A: POST /v1/webhooks/transactions
    A->>P: Insert transaction (PROCESSING)
    A->>P: Insert outbox event (PENDING)
    Note over A,P: Both inserts commit atomically
    A-->>C: 202 Accepted
    loop Dispatcher polling
        D->>P: Find due PENDING event
        D->>P: Claim event (lease + attempts++)
        D->>P: Commit claim
        D->>R: Publish Celery task
        D->>P: Mark DISPATCHED + dispatched_at
    end
    R->>W: Deliver task
    W->>P: Load transaction
    W->>W: Simulate processing (30 seconds)
    W->>P: Update status + processed_at
```

## 3. Outbox Dispatch and Retry Flow

```mermaid
flowchart TD
    Start([Dispatcher polling cycle]) --> Find{Eligible event found?}
    Find -- No --> Sleep["Wait poll interval"]
    Sleep --> Start
    Find -- Yes --> Claim["Claim event<br/>row lock / lease<br/>increment attempts"]
    Claim --> Publish{"Celery publish successful?"}
    Publish -- Yes --> Mark["Set status DISPATCHED<br/>set dispatched_at<br/>clear claim"]
    Mark --> Commit["Commit DB update"]
    Publish -- No --> Retry["Save last_error<br/>schedule next_attempt_at<br/>release claim"]
    Retry --> CommitRetry["Commit retry metadata"]
    Commit --> Start
    CommitRetry --> Start
```

## 4. Transaction Status Lifecycle

```mermaid
stateDiagram-v2
    [*] --> PROCESSING: Webhook accepted
    PROCESSING --> PROCESSED: Worker succeeds
    PROCESSING --> FAILED: Retry attempts exhausted
```

`DISPATCHED` is an **outbox event** state, not a transaction state. It means the dispatcher published the task to Celery; it does not mean transaction processing is complete.

## 5. Responsibility by Component

| Component | Responsibility |
|---|---|
| Webhook Client | Sends transaction webhook payload |
| FastAPI | Validates payload, applies idempotency, persists transaction and outbox event, returns HTTP 202 |
| PostgreSQL | Durable source of truth for transaction and outbox records |
| Outbox Dispatcher | Claims eligible events, publishes tasks, records dispatch status and schedules retries on publish errors |
| Redis | Celery task broker |
| Celery Worker | Processes transaction asynchronously and persists the final status/timestamp |
| Alembic | Applies database schema migrations |
| Pytest | Runs live end-to-end and recovery tests |

## 6. Reliability Notes

- **Idempotency:** the unique transaction ID prevents duplicate transaction records. The outbox event also has a uniqueness constraint on `(transaction_id, event_type)`.
- **Atomic persistence:** transaction and outbox event are inserted in the same database transaction, preventing an accepted transaction from being stored without its durable event.
- **Claiming:** the dispatcher uses a database row lock with `SKIP LOCKED` and a time-limited claim lease to coordinate dispatch attempts.
- **Dispatch retry:** publish errors record `last_error`, schedule `next_attempt_at`, and release the claim.
- **Worker retry:** transient processing errors request a Celery retry; retry exhaustion is covered by the recovery tests.
- **Processing delay:** the worker intentionally waits 30 seconds to model asynchronous processing for this assignment.

## 7. Local Development Processes

Run from the project root after activating `.venv`:

```cmd
python scripts\dev.py
```

The runner starts Docker Compose services, applies Alembic migrations, and launches separate Windows terminals for the API, dispatcher, and worker.

```mermaid
flowchart LR
    Runner["scripts/dev.py"] --> Compose["Docker Compose<br/>PostgreSQL + Redis"]
    Runner --> Migrations["Alembic upgrade head"]
    Runner --> API["FastAPI terminal"]
    Runner --> Dispatcher["Dispatcher terminal"]
    Runner --> Worker["Celery worker terminal"]
    API --> PostgreSQL[("PostgreSQL")]
    Dispatcher --> PostgreSQL
    Dispatcher --> Redis[("Redis")]
    Redis --> Worker
    Worker --> PostgreSQL
```

> **Implementation note:** diagrams document the currently described implementation. Keep them synchronized with the code if component names, retry behavior, or deployment topology change.
"""