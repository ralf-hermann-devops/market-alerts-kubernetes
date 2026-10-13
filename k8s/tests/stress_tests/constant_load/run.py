import subprocess
import sys
import time
from pathlib import Path

NAMESPACE = "trading-alerts"
DATABASE_POD = "postgres-0"
DATABASE = "alerts"
KUSTOMIZATION = Path(__file__).resolve().parent
JOB_NAME = "constant-load"
DATABASE_TIMEOUT_SECONDS = 30
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
    result = kubectl("exec", "-n", NAMESPACE, DATABASE_POD, "--", "psql", "-U", "app", "-d", DATABASE, "-tA",
                     "-c", "SELECT COUNT(*) FROM alerts;", capture_output=True)
    return int(result)


def show_job_logs(job_name: str) -> None:
    """Print logs for the named Job in the application namespace."""
    kubectl("logs", "-n", NAMESPACE, f"job/{job_name}")


def main() -> int:
    """Send a constant load via a Job and check for a new database row.

    Return zero when the row count increases, or a nonzero status on failure.
    """
    try:
        # Record the baseline before sending the test alert.
        before_count = alert_count()
        print(f"Alert rows before test: {before_count}")

        # Recreate the fixed-name Job so each run executes a fresh load test.
        kubectl("delete", "job", JOB_NAME,
            "-n",NAMESPACE,
            "--ignore-not-found=true")
        
        kubectl("apply", "-k", str(KUSTOMIZATION))


        try:
            job_duration_sec = kubectl("get", "job", JOB_NAME, "-n", NAMESPACE,
                "-o=jsonpath='{.spec.template.spec.containers[0].env[?(@.name==\"DURATION_SECONDS\")].value}'",
                capture_output=True)[1:-1] # the number comes wrapped in quotes e.g. '5'
            job_timout_sec = int(int(job_duration_sec)*1.5)
            kubectl("wait", "-n", NAMESPACE,
                "--for=condition=complete", f"job/{JOB_NAME}",
                f"--timeout={job_timout_sec}s",
            )
            show_job_logs(JOB_NAME)
        except subprocess.CalledProcessError:
            print("Job did not complete successfully; showing its logs.", file=sys.stderr)
            show_job_logs(JOB_NAME)
            return 1

        # TODO add test conditions after job termination
       
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