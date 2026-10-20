A FastAPI service for accepting transaction webhooks and processing them asynchronously with PostgreSQL, an outbox dispatcher, Redis, and Celery.

## Features

- Accept transaction webhooks with HTTP `202 Accepted`.
- Idempotent handling of repeated `transaction_id` values.
- Persist transactions and outbox events in PostgreSQL.
- Process transactions asynchronously using Celery.
- Retry handling for dispatch and worker failures.
- Query transaction status through the API.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for architecture diagrams and component details.

## Prerequisites

- Git
- Python 3.13
- Docker Desktop with Docker Compose

## Clone the repository

Replace `<your-public-repository-url>` with your actual GitHub repository URL:

```bash
git clone <your-public-repository-url>
cd transaction-webhook-service
```

## Local setup (Windows CMD)

### 1. Create and activate a virtual environment

```cmd
py -3.13 -m venv .venv
.venv\Scripts\activate.bat
```

### 2. Install dependencies

If the repository contains `requirements.txt`:

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

Use the same password in `POSTGRES_PASSWORD` and `DATABASE_URL`. These values are for local development only. Do not commit `.env` or real credentials.

### 4. Start the application

Make sure Docker Desktop is running, then run:

```cmd
python scripts\dev.py
```

The development runner starts Docker Compose services, applies Alembic migrations, and opens separate terminal windows for the API, outbox dispatcher, and Celery worker. Keep those windows open while using the service.

If startup fails, check that the service names in the Compose file and the environment variables in `.env` match your local configuration.

## Run tests

With the required services running:

```cmd
python scripts\dev.py test
```

Or run pytest directly:

```cmd
python -m pytest -v -s
```

The last reported local test run was `9 passed in 36.08s`. Run the tests again to verify your current environment.

## API endpoints

Base URL: `http://127.0.0.1:8000`

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/` | Health check |
| `POST` | `/v1/webhooks/transactions` | Submit a transaction webhook |
| `GET` | `/v1/transactions/{transaction_id}` | Get transaction status |

### Example: submit a transaction

```bash
curl -X POST http://127.0.0.1:8000/v1/webhooks/transactions ^
  -H "Content-Type: application/json" ^
  -d "{\"transaction_id\":\"txn_demo_001\",\"source_account\":\"account_100\",\"destination_account\":\"account_200\",\"amount\":\"12.50\",\"currency\":\"USD\"}"
```

A valid request returns HTTP `202 Accepted`. Repeating the same `transaction_id` should not create a duplicate transaction or outbox event.

### Example: get transaction status

```cmd
curl http://127.0.0.1:8000/v1/transactions/txn_demo_001
```

A new transaction starts with `PROCESSING` status. Successful background processing changes it to `PROCESSED`. A transaction whose worker retries are exhausted may be marked `FAILED`.

## Stop the application

Run:

```cmd
python scripts\dev.py stop
```

This stops application processes tracked by the runner. It does not delete PostgreSQL/Redis Docker volumes. To stop the Compose services as well, use:

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
├── ARCHITECTURE.md
└── README.md
```

## Notes

- The worker includes an intentional 30-second processing delay for the assignment.
- `DISPATCHED` is the outbox event status and means the task was published; it does not mean transaction processing has completed.
- Before submitting, replace the clone URL placeholder with the real public repository URL and verify that all documented files exist in the repository.
"""