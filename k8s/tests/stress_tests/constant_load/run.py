from pathlib import Path
import sys

TESTS_DIRECTORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TESTS_DIRECTORY))

from job_runner import run_job_and_check_alerts


def main() -> int:
    """Run the constant-load Job and verify its alerts were persisted."""
    return run_job_and_check_alerts(
        job_name="constant-load",
        kustomization=Path(__file__).resolve().parent,
        request_count_env="N_REQUESTS",
        job_timeout_seconds=660,
        database_timeout_seconds=240
    )


if __name__ == "__main__":
    raise SystemExit(main())