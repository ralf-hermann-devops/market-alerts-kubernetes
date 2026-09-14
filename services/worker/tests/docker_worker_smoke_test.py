import json
import os
import subprocess
import time
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
COMPOSE_FILE = ROOT / "Dockercompose.yaml"
PROJECT_NAME = f"worker-smoke-{os.getpid()}"
WAIT_TIMEOUT = 60

EVENTS = [
    {"symbol": "WORKERTEST1", "action": "long", "price": 101.25, "timeframe": "1m"},
    {"symbol": "WORKERTEST2", "action": "short", "price": 202.50, "timeframe": "5m"},
    {"symbol": "WORKERTEST3", "action": "long", "price": 303.75, "timeframe": "15m"},
]


def run(command, check=True, show_command=True):
    if show_command:
        print("$", " ".join(str(part) for part in command), flush=True)
    result = subprocess.run(command, capture_output=True, text=True)
    if check and result.returncode:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(str(part) for part in command)}"
            f"\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result


def compose(*args, check=True, show_command=True):
    return run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "-p",
            PROJECT_NAME,
            *args,
        ],
        check=check,
        show_command=show_command,
    )


def wait_for(description, *args):
    deadline = time.monotonic() + WAIT_TIMEOUT
    last_output = ""
    while time.monotonic() < deadline:
        result = compose(*args, check=False, show_command=False)
        last_output = (result.stdout + result.stderr).strip()
        if result.returncode == 0:
            return
        time.sleep(1)
    raise TimeoutError(f"Timed out waiting for {description}. Last output: {last_output}")


def wait_for_dependencies():
    wait_for("Redis", "exec", "-T", "redis", "redis-cli", "ping")
    wait_for("Postgres", "exec", "-T", "postgres", "pg_isready", "-U", "app", "-d", "alerts")


def enqueue_events():
    queued = []
    for event in EVENTS:
        payload = json.dumps(event, separators=(",", ":"))
        result = compose("exec", "-T", "redis", "redis-cli", "XADD", "alerts", "*", "payload",
            payload,
        )
        stream_id = result.stdout.strip()
        queued.append(
            (stream_id, event["symbol"], event["action"], Decimal(str(event["price"])), event["timeframe"])
        )
        print(f"Queued {event['symbol']} as stream entry {stream_id}")
    return queued


def read_processed_events(show_command=True):
    result = compose(
        "exec", "-T", "postgres", "psql", "-U", "app", "-d", "alerts", "-At", "-F", "|", "-c",
        "SELECT stream_id, symbol, action, price::text, timeframe FROM alerts "
        "WHERE symbol LIKE 'WORKERTEST%' ORDER BY symbol",
        show_command=show_command,
    )
    rows = []
    for line in result.stdout.splitlines():
        if line.strip():
            stream_id, symbol, action, price, timeframe = line.strip().split("|")
            rows.append((stream_id, symbol, action, Decimal(price), timeframe))
    return rows


def wait_for_processed_events(expected):
    expected = sorted(expected, key=lambda event: event[1])
    deadline = time.monotonic() + WAIT_TIMEOUT
    actual = []
    while time.monotonic() < deadline:
        actual = read_processed_events(show_command=False)
        if actual == expected:
            return True, actual
        time.sleep(1)
    return False, actual


def print_worker_logs():
    result = compose("logs", "--no-color", "worker", check=False)
    if result.stdout:
        print("\nWorker logs:\n" + result.stdout)
    if result.stderr:
        print(result.stderr)


def main():
    if not COMPOSE_FILE.is_file():
        raise FileNotFoundError(f"Compose file not found: {COMPOSE_FILE}")

    try:
        compose("up", "-d", "redis", "postgres")
        wait_for_dependencies()
        compose("up", "--build", "-d", "worker")
        expected = enqueue_events()
        passed, processed = wait_for_processed_events(expected)
        status = "passed" if passed else "failed"
        print(f"\n{status}: Worker smoke test")
        if not passed:
            print(f"Expected: {expected}")
            print(f"Actual:   {processed}")
            print_worker_logs()
    except Exception:
        print_worker_logs()
        raise
    finally:
        compose("down", "--volumes", "--remove-orphans", check=False)


if __name__ == "__main__":
    main()
