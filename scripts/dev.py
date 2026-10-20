from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / ".runtime"
PID_FILE = RUNTIME_DIR / "dev_processes.json"
PYTHON = sys.executable

PROCESSES = {
    "api": [
        PYTHON,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ],
    "dispatcher": [PYTHON, "-m", "app.services.outbox_dispatcher"],
    "worker": [
        PYTHON,
        "-m",
        "celery",
        "-A",
        "app.celery_app:celery_app",
        "worker",
        "--loglevel=info",
        "--pool=solo",
    ],
}


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    print("+", subprocess.list2cmdline(command), flush=True)
    return subprocess.run(command, cwd=ROOT, check=check)


def require_venv() -> None:
    if sys.prefix == sys.base_prefix:
        raise SystemExit(
            "ERROR: Activate the project virtual environment first.\n"
            r"Run: .venv\Scripts\activate.bat"
        )


def compose_up() -> None:
    result = run(["docker", "compose", "up", "-d"], check=False)
    if result.returncode:
        raise SystemExit(
            "ERROR: Docker Compose could not start. Ensure Docker Desktop is running "
            "and docker-compose.yml/compose.yaml is present."
        )
    run(["docker", "compose", "ps"], check=False)


def migrate_with_retries() -> None:
    for attempt in range(1, 16):
        result = run([PYTHON, "-m", "alembic", "upgrade", "head"], check=False)
        if result.returncode == 0:
            return
        if attempt < 15:
            print(
                f"Database/migration not ready yet ({attempt}/15); retrying in 2 seconds...",
                flush=True,
            )
            time.sleep(2)
    raise SystemExit(
        "ERROR: Alembic migration failed after retries. Check PostgreSQL and DATABASE_URL."
    )


def port_is_listening(host: str, port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


def load_pid_data() -> dict:
    if not PID_FILE.exists():
        return {}
    try:
        data = json.loads(PID_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_pid_data(data: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def start_processes() -> None:
    old = load_pid_data()
    if old:
        active = []
        for name, details in old.items():
            pid = details.get("pid") if isinstance(details, dict) else None
            if (
                pid
                and subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    capture_output=True,
                    text=True,
                    check=False,
                ).stdout.find(str(pid))
                >= 0
            ):
                active.append(name)
        if active:
            raise SystemExit(
                f"ERROR: Existing tracked processes may still be running: {', '.join(active)}. "
                "Run `python scripts\\dev.py stop` first."
            )

    if port_is_listening("127.0.0.1", 8000):
        raise SystemExit(
            "ERROR: Port 8000 is already in use. Stop the existing API before running dev."
        )

    launched = {}
    try:
        for name, command in PROCESSES.items():
            print(f"Starting {name} in a separate terminal...", flush=True)
            proc = subprocess.Popen(
                command,
                cwd=ROOT,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            launched[name] = {"pid": proc.pid, "command": command}
            save_pid_data(launched)
            time.sleep(0.5)
    except Exception:
        stop_processes()
        raise

    print("\nStartup commands launched.")
    print("API URL: http://127.0.0.1:8000/")
    print(
        "Wait for the API, dispatcher, and worker startup logs before running live E2E tests."
    )
    print("Stop the launched application processes with: python scripts\\dev.py stop")
    print("PostgreSQL/Redis containers are intentionally left running by `stop`.")


def stop_processes() -> None:
    data = load_pid_data()
    if not data:
        print("No tracked application processes found.")
        return

    for name, details in data.items():
        pid = details.get("pid") if isinstance(details, dict) else None
        if not pid:
            continue
        print(f"Stopping {name} (PID {pid})...")
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            cwd=ROOT,
            check=False,
        )
        if result.returncode not in (0, 128):
            print(f"Warning: taskkill returned {result.returncode} for {name}.")

    try:
        PID_FILE.unlink(missing_ok=True)
        if RUNTIME_DIR.exists() and not any(RUNTIME_DIR.iterdir()):
            RUNTIME_DIR.rmdir()
    except OSError as exc:
        print(f"Warning: could not clean runtime PID file: {exc}")
    print("Stop requested. Docker containers and database volumes were not deleted.")


def run_tests() -> None:
    require_venv()
    result = run([PYTHON, "-m", "pytest", "-v", "-s"], check=False)
    raise SystemExit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Windows-friendly development runner for Transaction Webhook Service."
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["dev", "test", "migrate", "infra", "stop"],
        default="dev",
        help="dev=start infrastructure, migrate, and app processes; test=pytest; "
        "migrate=apply Alembic migrations; infra=start Docker Compose; stop=stop tracked app processes",
    )
    args = parser.parse_args()
    os.chdir(ROOT)

    if args.command == "stop":
        stop_processes()
        return

    require_venv()
    if args.command == "infra":
        compose_up()
    elif args.command == "migrate":
        migrate_with_retries()
    elif args.command == "test":
        run_tests()
    else:
        compose_up()
        migrate_with_retries()
        start_processes()


if __name__ == "__main__":
    main()
