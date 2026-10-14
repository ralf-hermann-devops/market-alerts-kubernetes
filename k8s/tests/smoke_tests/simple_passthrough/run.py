from pathlib import Path
import sys

TESTS_DIRECTORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TESTS_DIRECTORY))

from job_runner import run_job_and_check_alerts


def main() -> int:
    """Run the passthrough Job and verify its alerts were persisted."""
    return run_job_and_check_alerts(
        job_name="simple-passthrough",
        kustomization=Path(__file__).resolve().parent,
        request_count_env="REQUEST_COUNT",
        job_timeout_seconds=120,
        database_timeout_seconds=30
    )


if __name__ == "__main__":
    raise SystemExit(main())