A FastAPI service for accepting transaction webhooks and processing them asynchronously with PostgreSQL, a transactional outbox, Redis, and Celery.

## Features

- Accept transaction webhooks with HTTP `202 Accepted`.
- Idempotent handling of repeated `transaction_id` values.
- Persist transactions and outbox events in PostgreSQL.
- Process transactions asynchronously using Celery.
- Retry handling for dispatch and worker failures.
- Query transaction status through the API.
- Automated end-to-end and recovery tests.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for architecture diagrams, request flow, retry behavior, and component responsibilities.

## Technology choices

- **FastAPI** — request validation and HTTP API.
- **PostgreSQL** — durable transaction and outbox-event storage.
- **Transactional outbox** — stores the transaction and its dispatchable event atomically.
- **Redis + Celery** — background task broker and worker execution.
- **SQLAlchemy + Alembic** — database access and schema migrations.
- **Pytest + HTTPX** — automated tests, including live API integration tests.

## Prerequisites

- Git
- Python 3.13
- Docker Desktop with Docker Compose

## Clone the repository

```bash
git clone git@github.com:shujaa786/transaction-webhook-service.git
cd transaction-webhook-service
```

SSH cloning requires an SSH key configured with your GitHub account. If you have not configured SSH, use the repository's HTTPS clone URL instead.

## Local setup (Windows CMD)

### 1. Create and activate a virtual environment

```cmd
py -3.13 -m venv .venv
.venv\Scripts\activate.bat
```

### 2. Install dependencies

```cmd
python -m pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file in the project root:

```dotenv
POSTGRES_DB=transactions_db
POSTGRES_USER=transaction_app
POSTGRES_PASSWORD=replace_with_a_local_password
DATABASE_URL=postgresql+psycopg://transaction_app:replace_with_a_local_password@127.0.0.1:5433/transactions_db
REDIS_URL=redis://localhost:6379/0
```

Use the same password in `POSTGRES_PASSWORD` and `DATABASE_URL`. These are local-development values; do not commit `.env` or real credentials.

### 4. Start the application

Make sure Docker Desktop is running, then run:

```cmd
python scripts\dev.py
```

The development runner starts Docker Compose services, applies Alembic migrations, and opens separate terminal windows for the API, outbox dispatcher, and Celery worker. Keep those windows open while using the service.

If startup fails, check that the Docker Compose services and environment variables match your local configuration.

## API documentation

Base URL: `http://127.0.0.1:8000`

When the FastAPI application's default documentation routes are enabled:

- **Swagger UI:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc:** [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)
- **OpenAPI schema:** [http://127.0.0.1:8000/openapi.json](http://127.0.0.1:8000/openapi.json)

These routes are provided by FastAPI unless they have been disabled or customized in the application configuration.

## API endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/` | Health check |
| `POST` | `/v1/webhooks/transactions` | Submit a transaction webhook |
| `GET` | `/v1/transactions/{transaction_id}` | Get transaction status |

### Health check

```cmd
curl http://127.0.0.1:8000/
```

The response contains `status` and `current_time`.

### Submit a transaction

`POST /v1/webhooks/transactions`

Example request using the assignment's sample field types:

```json
{
  "transaction_id": "txn_abc123def456",
  "source_account": "acc_user_789",
  "destination_account": "acc_merchant_456",
  "amount": 1500,
  "currency": "INR"
}
```

A valid request returns HTTP `202 Accepted`. The transaction and its outbox event are persisted before acknowledgement. Repeating the same `transaction_id` should not create a duplicate transaction or outbox event.

### Get transaction status

`GET /v1/transactions/{transaction_id}`

```cmd
curl http://127.0.0.1:8000/v1/transactions/txn_abc123def456
```

The response includes transaction details, status, `created_at`, and `processed_at`. A new transaction starts with `PROCESSING`; successful background processing changes it to `PROCESSED`. If worker retries are exhausted, the recovery path can mark it `FAILED`.

## Run tests

Start the infrastructure, API, dispatcher, and worker first because the live end-to-end tests use running services.

```cmd
python scripts\dev.py test
```

Or run pytest directly:

```cmd
python -m pytest -v -s
```

The test suite covers:

- Health endpoint response contract.
- Real webhook POST and transaction persistence.
- Duplicate delivery without duplicate transaction/outbox records.
- Outbox dispatch state and `dispatched_at` timestamp.
- Background worker processing and final transaction status.
- Invalid payload validation and unknown-transaction `404`.
- Dispatch failure retry scheduling and claim release.
- Successful dispatch timestamp and claim cleanup.
- Recovery of expired claims.
- Worker transient retry behavior and retry-exhaustion failure persistence.

**Last reported local result:** `9 passed in 36.08s`. Re-run the suite after changes; this result describes that run, not a guarantee for every environment.

## Stop the application

```cmd
python scripts\dev.py stop
```

This stops application processes tracked by the runner. It does not delete PostgreSQL/Redis Docker volumes. To stop Compose services as well:

```cmd
docker compose stop
```

## Project structure

```text
.
├── app/
│   ├── api/
│   ├── core/
│   ├── db/
│   ├── schemas/
│   ├── services/
│   └── tasks/
├── alembic/
├── scripts/
│   └── dev.py
├── tests/
│   ├── test_e2e_live.py
│   └── test_recovery.py
├── ARCHITECTURE.md
└── README.md
```

## Notes

- The worker includes an intentional 30-second processing delay for the assignment.
- `DISPATCHED` is an outbox-event status: it means the task was published to Celery, not that transaction processing has finished.
- Keep `.env`, passwords, and other secrets out of version control.
