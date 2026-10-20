Transaction Webhook Service — Windows dev runner

Prerequisites:
- Docker Desktop running
- Project virtual environment created and dependencies installed
- .env configured with the project DATABASE_URL and REDIS_URL
- Run commands from the project root, with .venv activated

Commands:
  .venv\Scripts\activate.bat
  python scripts\dev.py
  python scripts\dev.py test
  python scripts\dev.py migrate
  python scripts\dev.py infra
  python scripts\dev.py stop

Default command (`dev`) runs `docker compose up -d`, retries Alembic migrations,
then opens separate Windows terminals for the API, outbox dispatcher, and Celery
worker. It assumes the existing project entry points:
- app.main:app
- app.services.outbox_dispatcher
- app.celery_app:celery_app

`stop` terminates only the app processes launched and tracked by this script.
It does not stop containers, delete Docker volumes, or alter database records.

Review before use:
- `docker compose up -d` starts all services defined in the Compose project.
  If your Compose file also defines an application service you do not want started,
  adjust `compose_up()` in scripts/dev.py to name only your infrastructure services.
- On Windows the Celery worker uses `--pool=solo`.
- The runner was generated from the currently described project structure; it has
  not been executed against your local project here. If a command/entry point differs,
  share the exact output and adjust based on that evidence.
