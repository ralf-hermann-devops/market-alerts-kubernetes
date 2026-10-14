import subprocess
import sys
import time
from datetime import datetime, timezone

from pathlib import Path

NAMESPACE = "trading-alerts"
DEPLOYMENTS = ("api", "worker", "redis")
STATEFULSETS = ("postgres",)
FETCHER_CRONJOB = "market-data-fetcher"
TIMEOUT_SECONDS = 120
POLL_INTERVAL_SECONDS = 2

TESTS_DIRECTORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TESTS_DIRECTORY))

from job_runner import kubectl


def wait_for_workload(resource: str, name: str) -> None:
    """Wait for a workload rollout, raising CalledProcessError if kubectl fails."""
    kubectl("rollout", "status", f"{resource}/{name}",
        "--namespace", NAMESPACE,
        f"--timeout={TIMEOUT_SECONDS}s",
    )
    print(f"{resource}/{name} is ready.")

def main() -> int:
    """Check configured Deployment and StatefulSet rollouts.

    Return zero on success or 1 for handled errors; subprocess failures propagate.
    """
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
