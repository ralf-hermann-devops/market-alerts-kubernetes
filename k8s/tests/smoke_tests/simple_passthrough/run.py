import subprocess
import sys
import time
from pathlib import Path

NAMESPACE = "trading-alerts"
DATABASE_POD = "postgres-0"
DATABASE = "alerts"
MANIFEST = Path(__file__).resolve().with_name("send_to_api.yaml")
JOB_TIMEOUT_SECONDS = 120
DATABASE_TIMEOUT_SECONDS = 30
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


def alert_count() -> int:
    result = kubectl("exec", "-n", NAMESPACE, DATABASE_POD, "--", "psql", "-U", "app", "-d", DATABASE, "-tA",
                     "-c", "SELECT COUNT(*) FROM alerts;", capture_output=True)
    return int(result)


def show_job_logs(job_name: str) -> None:
    kubectl("logs", "-n", NAMESPACE, f"job/{job_name}")


def main() -> int:
    try:
        # Record the baseline before sending the test alert.
        before_count = alert_count()
        print(f"Alert rows before test: {before_count}")

        # Create this run's uniquely named Job and wait for it to finish.
        created_job = kubectl("create","-f", str(MANIFEST), "-o", "name", capture_output=True)
        job_name = created_job.split("/", maxsplit=1)[-1]
        print(f"Created {job_name}")

        try:
            kubectl("wait", "-n", NAMESPACE,
                "--for=condition=complete", f"job/{job_name}",
                f"--timeout={JOB_TIMEOUT_SECONDS}s",
            )
            show_job_logs(job_name)
        except subprocess.CalledProcessError:
            print("Job did not complete successfully; showing its logs.", file=sys.stderr)
            show_job_logs(job_name)
            return 1            
            
        # The worker writes asynchronously, so poll for the expected new row.
        deadline = time.monotonic() + DATABASE_TIMEOUT_SECONDS
        after_count = alert_count()
        while after_count <= before_count and time.monotonic() < deadline:
            time.sleep(POLL_INTERVAL_SECONDS)
            after_count = alert_count()

        print(f"Alert rows after test:  {after_count}")

        # Fail if the Job completed but the alert was not persisted.
        if after_count <= before_count:
            print(
                "The API test Job completed, but no new alert row appeared "
                f"within {DATABASE_TIMEOUT_SECONDS} seconds.",
                file=sys.stderr,
            )
            return 1

        print(f"Database row count increased by {after_count - before_count}.")
        return 0
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


if __name__ == "__main__":
    raise SystemExit(main())