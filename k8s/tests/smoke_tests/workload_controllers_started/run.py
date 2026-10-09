import subprocess
import sys
import time
from datetime import datetime, timezone

NAMESPACE = "trading-alerts"
DEPLOYMENTS = ("api", "worker", "redis")
STATEFULSETS = ("postgres",)
FETCHER_CRONJOB = "market-data-fetcher"
TIMEOUT_SECONDS = 120
POLL_INTERVAL_SECONDS = 2


def kubectl(*args: str, capture_output: bool = False) -> str:
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


def wait_for_workload(resource: str, name: str) -> None:
    kubectl("rollout", "status", f"{resource}/{name}",
        "--namespace", NAMESPACE,
        f"--timeout={TIMEOUT_SECONDS}s",
    )
    print(f"{resource}/{name} is ready.")

def main() -> int:
    try:
        for deployment in DEPLOYMENTS:
            wait_for_workload("deployment", deployment)
        for statefulset in STATEFULSETS:
            wait_for_workload("statefulset", statefulset)

        job_name = "component-startup-check-" + datetime.now(timezone.utc).strftime(
            "%Y%m%d%H%M%S%f"
        )

    except FileNotFoundError as error:
        print(f"Required command not found: {error.filename}", file=sys.stderr)
        return 1
    except (RuntimeError, TimeoutError) as error:
        print(str(error), file=sys.stderr)
        return 1

    print("All application components started successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
