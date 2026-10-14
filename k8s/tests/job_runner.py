import json
import subprocess
import sys
import time
from pathlib import Path

NAMESPACE = "trading-alerts"
DATABASE_POD = "postgres-0"
DATABASE = "alerts"
REDIS_STREAM = "alerts"
REDIS_GROUP = "workers"
POLL_INTERVAL_SECONDS = 2


def kubectl(*args: str, capture_output: bool = False) -> str:
    """Run kubectl, printing diagnostics and re-raising command failures.

    Return stripped stdout when capturing; otherwise print output and return "".
    """
    command = ["kubectl", *args]
    print(f"$ {' '.join(command)}", flush=True)
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as error:
        if error.stdout:
            print("stdout:", file=sys.stderr)
            print(error.stdout, end="", file=sys.stderr)
        if error.stderr:
            print("stderr:", file=sys.stderr)
            print(error.stderr, end="", file=sys.stderr)
        raise

    if not capture_output:
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
    return result.stdout.strip() if capture_output else ""


def alert_count() -> int:
    """Query PostgreSQL through kubectl and return the number of stored alerts."""
    result = kubectl("exec", "-n", NAMESPACE,DATABASE_POD,
        "--", "psql", "-U", "app", "-d", DATABASE, "-tA","-c",
        "SELECT COUNT(*) FROM alerts;",
        capture_output=True)
    return int(result)


def redis_queue_counts() -> tuple[int | None, int]:
    """Return the Redis Stream unread lag and pending count for the worker group."""
    result = kubectl("exec", "-n", NAMESPACE, "deployment/redis", "-c", "redis",
                     "--", "sh", "-c", 
                     f'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --json XINFO GROUPS {REDIS_STREAM}',
                     capture_output=True)
    groups = json.loads(result)
    if not isinstance(groups, list):
        raise ValueError("Redis XINFO GROUPS returned an unexpected response")

    group = None
    for item in groups:
        if isinstance(item, dict) and item.get("name") == REDIS_GROUP:
            group = item
            break
    if group is None:
        raise RuntimeError(
            f"Redis consumer group {REDIS_GROUP!r} was not found "
            f"for stream {REDIS_STREAM!r}"
        )

    lag = group.get("lag")
    pending = group.get("pending")
    if lag is not None and not isinstance(lag, int):
        raise ValueError("Redis consumer group returned an invalid unread lag")
    if not isinstance(pending, int):
        raise ValueError("Redis consumer group returned an invalid pending count")
    return lag, pending


def run_job_and_check_alerts(*,
                            job_name: str,
                            kustomization: Path,
                            request_count_env: str,
                            job_timeout_seconds: int,
                            database_timeout_seconds: int,
                        ) -> int:
    """Run a Kubernetes Job and verify its requests were persisted as alerts."""
    try:
        unread_count, pending_count = redis_queue_counts()
        before_count = alert_count()
        print(f"Alert rows before test: {before_count}")

        kubectl("delete","job", job_name, "-n", NAMESPACE,
                    "--ignore-not-found=true")
        kubectl("apply", "-k", str(kustomization))

        try:
            kubectl("wait", "-n", NAMESPACE,
                "--for=condition=complete",
                f"job/{job_name}",
                f"--timeout={job_timeout_seconds}s")
            kubectl("logs", "-n", NAMESPACE, f"job/{job_name}")
        except subprocess.CalledProcessError:
            print("Job did not complete successfully; showing its logs.", file=sys.stderr)
            kubectl("logs", "-n", NAMESPACE, f"job/{job_name}")
            return 1

        request_count = int(
            kubectl("get", "job", job_name, "-n", NAMESPACE,
                "-o=jsonpath={.spec.template.spec.containers[0].env[?(@.name=="
                f'"{request_count_env}"' + ")].value}",
                capture_output=True
            )
        )

        deadline = time.monotonic() + database_timeout_seconds
        after_count = before_count
        while time.monotonic() < deadline:
            after_count = alert_count()
            if after_count == before_count + request_count:
                print(f"Database row count increased by {after_count - before_count}.")
                return 0
            time.sleep(POLL_INTERVAL_SECONDS)

        unread_count, pending_count = redis_queue_counts()
        unread_status = (
            "unavailable (Redis could not calculate lag)"
            if unread_count is None
            else str(unread_count)
        )
        print(
            "The API test Job completed, but not all new alert rows appeared "
            f"within {database_timeout_seconds} seconds. Expected increase: "
            f"{request_count}; actual increase: {after_count - before_count}. "
            f"Redis unread alerts: {unread_status}; pending alerts: {pending_count}.",
            file=sys.stderr,
        )
        return 1
    except FileNotFoundError as error:
        print(f"Required command not found: {error.filename}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        print(
            f"Command failed with exit code {error.returncode}: "
            f"{' '.join(error.cmd)}",
            file=sys.stderr,
        )
        return error.returncode or 1
