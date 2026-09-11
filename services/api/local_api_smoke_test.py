import json
import shlex
import subprocess
from pathlib import Path
import time


API_DIR = Path(__file__).resolve().parent
IMAGE_NAME = "app-api-local_api-smoketest"
CONTAINER_NAME = "api-local_api-smoketest"
REDIS_NAME = "redis-local_api-smoketest"
BUSYBOX_NAME = "api-smoke-busybox_api-smoketest"
NETWORK_NAME = "api-local-net_api-smoketest"


def run(cmd, check=True, cwd=None):
    print("$", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(cmd)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    return result


def request_http(path, timeout=30):
    deadline = time.time() + timeout
    last_output = ""

    while time.time() < deadline:
        container_name_busy_box = f"api-check-{path.strip('/').replace('/', '-') or 'root'}"
        run(["docker", "rm", "-f", container_name_busy_box], check=False)
        cmd = (
            f"wget -T 5 -q -O - http://{CONTAINER_NAME}:8000{path} 2>&1"
        )
        result = run([
            "docker", "run", "--rm",
            "--network", NETWORK_NAME,
            "--name", container_name_busy_box,
            "busybox:1.36",
            "sh", "-c",
            cmd,
        ], check=False)
        combined = (result.stdout + result.stderr).strip()
        if result.returncode == 0 and combined:
            return combined
        last_output = combined
        time.sleep(1)

    return last_output


def ensure_network():
    result = run(["docker", "network", "inspect", NETWORK_NAME], check=False)
    if result.returncode != 0:
        run(["docker", "network", "create", NETWORK_NAME])


def ensure_redis():
    result = run(["docker", "ps", "-a", "--filter", f"name=^{REDIS_NAME}$", "--format", "{{.Names}}"], check=False)
    if result.stdout.strip() != REDIS_NAME:
        run([
            "docker", "run", "-d",
            "--name", REDIS_NAME,
            "--network", NETWORK_NAME,
            "-p", "6379:6379",
            "redis:7-alpine",
        ])


def build_image():
    run(["docker", "build", "-t", IMAGE_NAME, "."], cwd=str(API_DIR))


def start_api():
    run(["docker", "rm", "-f", CONTAINER_NAME], check=False)
    run([
        "docker", "run", "-d",
        "--name", CONTAINER_NAME,
        "--network", NETWORK_NAME,
        "-p", "8000:8000",
        "-e", f"REDIS_URL=redis://{REDIS_NAME}:6379/0",
        "-e", "DATABASE_URL=postgresql://app:app@host.docker.internal:5432/alerts",
        "-e", "WEBHOOK_SECRET=dev-secret",
        IMAGE_NAME,
    ])


def send_webhook(secret, symbol="AAPL", action="long", price=123.45, timeframe="1h"):
    payload = json.dumps({
        "secret": secret,
        "symbol": symbol,
        "action": action,
        "price": price,
        "timeframe": timeframe,
    }, separators=(",", ":"))
    payload_arg = shlex.quote(payload)

    run([
        "docker", "rm", "-f", BUSYBOX_NAME,
    ], check=False)
    result = run([
        "docker", "run", "--rm",
        "--network", NETWORK_NAME,
        "--name", BUSYBOX_NAME,
        "busybox:1.36",
        "sh", "-c",
        f"wget -S -O - --header='Content-Type: application/json' --post-data={payload_arg} http://{CONTAINER_NAME}:8000/webhook/tradingview",
    ], check=False)
    output = (result.stdout or result.stderr).strip()
    return {
        "status_code": result.returncode,
        "body": output,
    }


def test_endpoints():
    print("\nChecking /healthz")
    healthz_result = request_http("/healthz")
    print(healthz_result)

    print("\nChecking /readyz")
    readyz_result = request_http("/readyz")
    print(readyz_result)

    print("\nPosting valid webhook via busybox")
    valid_webhook_result = send_webhook("dev-secret")
    print(valid_webhook_result)

    print("\nPosting invalid webhook via busybox")
    invalid_webhook_result = send_webhook("wrong-secret")
    print(invalid_webhook_result)

    results = {
        "healthz": healthz_result,
        "readyz": readyz_result,
        "valid_webhook": valid_webhook_result,
        "invalid_webhook": invalid_webhook_result,
    }
    return results


def summarize_results(results):
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
    run(["docker", "rm", "-f", CONTAINER_NAME], check=False)
    run(["docker", "rm", "-f", REDIS_NAME], check=False)
    run(["docker", "rm", "-f", BUSYBOX_NAME], check=False)
    run(["docker", "network", "rm", NETWORK_NAME], check=False)


if __name__ == "__main__":
    try:
        ensure_network()
        ensure_redis()
        build_image()
        start_api()
        time.sleep(10)  # wait for the API to start
        results = test_endpoints()
        print("\nProcessed results:")
        print(results)
        print("\nSummary:")
        for line in summarize_results(results):
            print(line)
    finally:
        cleanup()
