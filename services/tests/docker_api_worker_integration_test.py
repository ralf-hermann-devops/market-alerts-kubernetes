import json
import os
import re
import shlex
import subprocess
import time
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "Dockercompose.yaml"
PROJECT_NAME = f"api-worker-integration-{os.getpid()}"
WAIT_TIMEOUT = 60
EVENT = {
    "symbol": f"E2E{os.getpid()}",
    "action": "long",
    "price": 123.45,
    "timeframe": "1h",
}


def run(command, check=True):
    print("$", " ".join(str(part) for part in command), flush=True)
    result = subprocess.run(command, capture_output=True, text=True)
    if check and result.returncode:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(str(part) for part in command)}"
            f"\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result


def compose(*args, check=True):
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
    )


def compose_service_environment(service):
    result = compose("config", "--format", "json")
    config = json.loads(result.stdout)
    return config["services"][service].get("environment", {})


def request_api(path, payload=None):
    command = "wget -S -T 5 -O -"
    if payload is not None:
        serialized_payload = json.dumps(payload, separators=(",", ":"))
        command += (
            " --header='Content-Type: application/json'"
            f" --post-data={shlex.quote(serialized_payload)}"
        )
    command += f" http://api:8000{path}"

    result = compose("run", "--rm", "--no-deps", "smoke-client", command, check=False)
    status_match = re.search(r"HTTP/\d+(?:\.\d+)?\s+(\d{3})", result.stderr)
    return {
        "status_code": int(status_match.group(1)) if status_match else None,
        "returncode": result.returncode,
        "body": result.stdout.strip(),
    }


def wait_for_api():
    deadline = time.monotonic() + WAIT_TIMEOUT
    last_result = None
    while time.monotonic() < deadline:
        last_result = request_api("/readyz")
        if last_result["status_code"] == 200 and '"ready":true' in last_result["body"]:
            return
        time.sleep(1)
    raise TimeoutError(f"API did not become ready. Last response: {last_result}")


def read_processed_event():
    query = (
        "SELECT stream_id, symbol, action, price::text, timeframe "
        f"FROM alerts WHERE symbol = '{EVENT['symbol']}' ORDER BY id"
    )
    result = compose(
        "exec",
        "-T",
        "postgres",
        "sh",
        "-c",
        'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F "|" '
        f'-c "{query}"',
    )
    rows = []
    for line in result.stdout.splitlines():
        if line.strip():
            stream_id, symbol, action, price, timeframe = line.strip().split("|")
            rows.append((stream_id, symbol, action, Decimal(price), timeframe))
    return rows


def wait_for_processed_event(expected):
    deadline = time.monotonic() + WAIT_TIMEOUT
    actual = []
    while time.monotonic() < deadline:
        actual = read_processed_event()
        if len(actual) == 1 and actual[0][1:] == expected:
            return actual
        time.sleep(1)
    raise TimeoutError(f"Worker did not persist the webhook. Expected fields: {expected}; actual: {actual}")


def print_service_logs():
    result = compose("logs", "--no-color", "api", "worker", check=False)
    if result.stdout:
        print("\nAPI and worker logs:\n" + result.stdout)
    if result.stderr:
        print(result.stderr)


def main():
    if not COMPOSE_FILE.is_file():
        raise FileNotFoundError(f"Compose file not found: {COMPOSE_FILE}")

    try:
        compose("up", "--build", "-d", "api", "worker", "redis", "postgres")
        wait_for_api()

        response = request_api(
            "/webhook/tradingview",
            {"secret": compose_service_environment("api")["WEBHOOK_SECRET"], **EVENT},
        )
        if (
            response["returncode"] != 0
            or response["status_code"] != 202
            or '"status":"queued"' not in response["body"]
        ):
            raise AssertionError(f"API did not accept the webhook: {response}")
        print(f"API accepted webhook for {EVENT['symbol']} (HTTP {response['status_code']})")

        expected = (
            EVENT["symbol"],
            EVENT["action"],
            Decimal(str(EVENT["price"])),
            EVENT["timeframe"],
        )
        rows = wait_for_processed_event(expected)
        if not re.fullmatch(r"\d+-\d+", rows[0][0]):
            raise AssertionError(f"Unexpected Redis stream ID persisted by worker: {rows[0][0]}")
        print(f"Worker persisted webhook to Postgres: {rows[0]}")
        print("\nPassed: API-to-worker integration test")
    except Exception:
        print_service_logs()
        raise
    finally:
        compose("down", "--volumes", "--remove-orphans", check=False)


if __name__ == "__main__":
    main()
