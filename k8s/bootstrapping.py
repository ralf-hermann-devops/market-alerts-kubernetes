#!/usr/bin/env python3

import re
import subprocess
import sys
from pathlib import Path

from create_sealed_secret import main as create_sealed_secret




KUSTOMIZATION_FILES = (
    "kustomization.yaml",
    "kustomization.yml",
    "Kustomization",
    "Kustomization.yaml",
    "Kustomization.yml",
)


def run(*args):
    print(f"$ {' '.join(args)}")

    result = subprocess.run(args)

    if result.returncode != 0:
        sys.exit(result.returncode)


def wait_for_crd(crd, timeout=120):
    print(f"Waiting for CRD {crd}...")

    run(
        "kubectl",
        "wait",
        "--for=condition=Established",
        f"crd/{crd}",
        f"--timeout={timeout}s",
    )
    print(f"CRD {crd} is established.")


def find_overlays(overlays_dir):
    if not overlays_dir.is_dir():
        print(f"Overlay directory not found: {overlays_dir}", file=sys.stderr)
        sys.exit(1)

    overlays = sorted(
        (
            overlay
            for overlay in overlays_dir.iterdir()
            if overlay.is_dir()
            and any((overlay / filename).is_file() for filename in KUSTOMIZATION_FILES)
        ),
        key=lambda overlay: overlay.name.casefold(),
    )

    if not overlays:
        print(f"No Kustomize overlays found in {overlays_dir}.", file=sys.stderr)
        sys.exit(1)

    return overlays


def choose_overlay(overlays):
    print("Available overlays:")
    for index, overlay in enumerate(overlays, start=1):
        print(f"  {index}. {overlay.name}")

    while True:
        try:
            selection = input("Select an overlay by number: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nOverlay selection cancelled.", file=sys.stderr)
            sys.exit(1)

        try:
            selected_index = int(selection)
        except ValueError:
            print("Enter the number of one of the listed overlays.")
            continue

        if 1 <= selected_index <= len(overlays):
            selected = overlays[selected_index - 1]
            print(f"Selected overlay: {selected.name}")
            return selected
        else:
            print(f"Choose a number from 1 to {len(overlays)}.")


def apply_infrastructure(infrastructure_dir):
    command = ["kubectl", "kustomize", "--enable-helm", str(infrastructure_dir)]
    print(f"$ {' '.join(command)}")

    build = subprocess.run(command, capture_output=True, text=True)
    if build.stderr:
        print(build.stderr, file=sys.stderr, end="")
    if build.returncode != 0:
        sys.exit(build.returncode)

    documents = re.split(r"(?m)^---\s*$", build.stdout)
    crds = []
    resources = []
    for document in documents:
        if re.search(r"(?m)^kind:\s*CustomResourceDefinition\s*$", document):
            crds.append(document)
        else:
            resources.append(document)

    for manifests, options in (
        (crds, ["--server-side", "--force-conflicts"]),
        (resources, []),
    ):
        if not manifests:
            continue

        apply_command = ["kubectl", "apply", *options, "-f", "-"]
        print(f"$ {' '.join(apply_command)}")
        result = subprocess.run(
            apply_command,
            input="\n---\n".join(manifests),
            text=True,
        )
        if result.returncode != 0:
            sys.exit(result.returncode)


def main():
    k8s_dir = Path(__file__).resolve().parent
    selected_overlay = choose_overlay(find_overlays(k8s_dir / "overlays"))

    # Phase 1: Install external infrastructure: KEDA + sealed secrets.
    apply_infrastructure(k8s_dir / "infrastructure")

    # The CRD must exist before we can create a ScaledObject.
    wait_for_crd("scaledobjects.keda.sh")
    wait_for_crd("sealedsecrets.bitnami.com")


    # Phase 2: Install the application overlay, which may contain custom resources.
    # -------
    # We intentionally do not wait for the KEDA operator to be ready.
    # Kubernetes can create the Custom Resources as soon as its CRD exists.
    # Once controllers start, it will discover and reconcile the existing resource.
    secret_creation_status = create_sealed_secret()
    if secret_creation_status != 0:
        sys.exit(secret_creation_status)
    run("kubectl", "apply", "-k", str(selected_overlay))

    print("Deployment completed successfully.")


if __name__ == "__main__":
    main()