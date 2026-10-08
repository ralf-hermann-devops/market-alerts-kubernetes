#!/usr/bin/env python3

import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
IMAGES = ("trading-api:dev", "trading-worker:dev", "trading-fetcher:dev")


def run(command: list[str]) -> None:
    print(f"$ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def main() -> int:
    try:
        run(["minikube", "status"])
        run(["docker", "compose", "-f", "Dockercompose.yaml", "build", "api", "worker", "fetcher"])
        for image in IMAGES:
            run(["minikube", "image", "load", image])
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


if __name__ == "__main__":
    raise SystemExit(main())
