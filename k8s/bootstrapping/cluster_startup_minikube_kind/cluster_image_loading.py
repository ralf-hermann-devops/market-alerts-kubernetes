import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
IMAGES = ("trading-api:dev", "trading-worker:dev", "trading-fetcher:dev")


def run(command: list[str]) -> None:
    """Run a command from the project root, raising CalledProcessError on failure."""
    print(f"$ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def output(command: list[str]) -> str:
    """Run a command from the project root and return stdout, raising on failure."""
    print(f"$ {' '.join(command)}", flush=True)
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    return result.stdout


def build_images() -> None:
    """Build the API, worker, and fetcher images using Docker Compose."""
    run(["docker", "compose", "-f", "Dockercompose.yaml", "build", "api", "worker", "fetcher"])


def select_existing_clusters(platform: str, clusters: list[str]) -> list[str] | None:
    """Prompt for cluster names; return None if none exist or selection is declined."""
    if not clusters:
        print(f"No existing {platform} clusters found.")
        return None

    print(f"Existing {platform} clusters:")
    for index, name in enumerate(clusters, start=1):
        print(f"  {index}. {name}")

    while True:
        answer = input(f"Load images into existing {platform} cluster(s)? [y/n]: ").strip().lower()
        if answer in ("n", "no"):
            return None
        if answer in ("y", "yes"):
            break
        print("Please answer 'y' or 'n'.")

    while True:
        selection = input("Enter cluster number(s) separated by commas, or 'all': ").strip()
        if selection.lower() == "all":
            return clusters
        try:
            indices = [int(value.strip()) for value in selection.split(",")]
        except ValueError:
            print("Enter valid cluster numbers separated by commas, or 'all'.")
            continue
        if indices and all(1 <= index <= len(clusters) for index in indices):
            # removed duplicate selections as dictionaries can only have unique keys
            return list(dict.fromkeys(clusters[index - 1] for index in indices))
        print("Select one or more cluster numbers from the list.")


def prompt_for_runs_cluster_name(platform: str, clusters: list[str], name_hint: str | None) \
        -> tuple[list[str], bool]:
    """Return selected cluster names and whether a new cluster must be created.

    Offer existing clusters first, then use name_hint or prompt for a name.
    """
    selected = select_existing_clusters(platform, clusters)
    if selected is not None:
        return selected, False

    # If no existing clusters were selected, prompt for a new cluster name
    name = (name_hint or "").strip()
    while True:
        if not name:
            name = input(f"Name for the new {platform} cluster: ").strip()
        if not name:
            print("The cluster name cannot be empty.")
        elif name in clusters:
            while True:
                answer = input(f"A {platform} cluster named '{name}' already exists. "
                    "Use that cluster? [y/n]: ").strip().lower()
                if answer in ("y", "yes"):
                    return [name], False
                if answer in ("n", "no"):
                    name = ""
                    break
                print("Please answer 'y' or 'n'.")
        else:
            return [name], True


def run_with_error_handling(action: Callable[[], None]) -> int:
    """Run an action and return zero on success, reporting command failures.

    Return 1 for a missing executable or the failed subprocess's exit code.
    Other exceptions propagate to the caller.
    """
    try:
        action()
    except FileNotFoundError as error:
        print(f"Required command not found: {error.filename}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        print(
            f"Command failed with exit code {error.returncode}: "
            f"{' '.join(error.cmd)}",
            file=sys.stderr,
        )
        return error.returncode
    return 0
