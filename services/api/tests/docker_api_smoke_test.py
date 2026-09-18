import json
import os
import shlex
import subprocess
from pathlib import Path
import time


ROOT = Path(__file__).resolve().parents[3]
COMPOSE_FILE = ROOT / "Dockercompose.yaml"
COMPOSE_PROJECT = f"api-smoke-{os.getpid()}"
CONTAINER_NAME = "api-local_api-smoketest"

def run(cmd, check=True, cwd=None):
    print("$", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(cmd)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    return result


def compose(*args, check=True):
    return run([
        "docker", "compose",
        "-f", str(COMPOSE_FILE),
        "-p", COMPOSE_PROJECT,
        *args,
    ], check=check)


def compose_service_environment(service):
    result = compose("config", "--format", "json")
    compose_config = json.loads(result.stdout)
    return compose_config["services"][service].get("environment", {})


def request_http(path, timeout=30):
    deadline = time.time() + timeout
    last_output = ""

    while time.time() < deadline:
        cmd = f"wget -T 5 -q -O - http://api:8000{path} 2>&1"
        result = compose("run", "--rm", "--no-deps", "smoke-client", cmd, check=False)
        combined = (result.stdout + result.stderr).strip()
        if result.returncode == 0 and combined:
            return combined
        last_output = combined
        time.sleep(1)

    return last_output


def ensure_redis():
    compose("up", "-d", "redis")


def build_image():
    compose("build", "api")


def start_api():
    compose("run", "-d", "--no-deps", "--use-aliases", "--name", CONTAINER_NAME, "api")


def send_webhook(secret, symbol="AAPL", action="long", price=123.45, timeframe="1h"):
    payload = json.dumps({
        "secret": secret,
        "symbol": symbol,
        "action": action,
        "price": price,
        "timeframe": timeframe,
    }, separators=(",", ":"))
    payload_arg = shlex.quote(payload)

    result = compose(
        "run", "--rm", "--no-deps", "smoke-client",
        f"wget -S -O - --header='Content-Type: application/json' "
        f"--post-data={payload_arg} http://api:8000/webhook/tradingview",
        check=False,
    )
    output = (result.stdout or result.stderr).strip()
    return {
        "status_code": result.returncode,
        "body": output,
    }


def test_endpoints(webhook_secret):
    print("\nChecking /healthz")
    healthz_result = request_http("/healthz")
    print(healthz_result)

    print("\nChecking /readyz")
    readyz_result = request_http("/readyz")
    print(readyz_result)

    print("\nPosting valid webhook via busybox")
    valid_webhook_result = send_webhook(webhook_secret)
    print(valid_webhook_result)

    print("\nPosting invalid webhook via busybox")
    invalid_webhook_result = send_webhook(webhook_secret + "ttttttt_010101")
    print(invalid_webhook_result)

    results = {
        "healthz": healthz_result,
        "readyz": readyz_result,
        "valid_webhook": valid_webhook_result,
        "invalid_webhook": invalid_webhook_result,
    }
    return results


def summarize_results(results):
    if results is None:
        return ["failed: All smoke tests, Got no results to summarize."]
    checks = [
        ("Healthz", results["healthz"], '{"ok":true}'),
        ("Readyz", results["readyz"], '{"ready":true}'),
        ("Valid Webhook", results["valid_webhook"]["body"], '{"status":"queued"}'),
        ("Invalid Webhook", results["invalid_webhook"]["body"], '401 Unauthorized'),
    ]

    output = []
    for label, actual, expected in checks:
        passed = expected in actual if actual else False
        status = "passed" if passed else "failed"
        output.append(f"{status}: {label}-test")
    return output


def cleanup():
    compose("down", "--volumes", "--remove-orphans", check=False)


if __name__ == "__main__":
    results = None
    try:
        api_environment = compose_service_environment("api")
        ensure_redis()
        build_image()
        start_api()
        time.sleep(5)  # wait for the API to start
        results = test_endpoints(api_environment["WEBHOOK_SECRET"])
    finally:
        cleanup()
        
        print("\nSummary:")
        for line in summarize_results(results):
            print(line)
