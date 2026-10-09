#!/usr/bin/env python3

import argparse
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path

from sealed_secrets_cli_args import SECRETS, validate_secret_args
from sealed_secrets_cli_args import create_parser as create_common_parser
from create_sealed_secret import main as create_sealed_secret

"""
To avoid initializing custom resources before their CRDs are established,
we split the deployment into two phases:
1. Install external infrastructure: KEDA + sealed secrets.
2. Install the application overlay, which may contain custom resources.
"""


KUSTOMIZATION_FILES = (
    "kustomization.yaml",
    "kustomization.yml",
    "Kustomization",
    "Kustomization.yaml",
    "Kustomization.yml",
)


def create_parser() -> argparse.ArgumentParser:
    parser = create_common_parser(
        "Bootstrap Kubernetes infrastructure and an application overlay."
    )
    parser.add_argument(
        "--overlay",
        help="Overlay directory name to apply (required for non-interactive mode if ambiguous)",
    )
    return parser


def run(*args):
    print(f"$ {' '.join(args)}")
    subprocess.run(args, check=True)


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
        raise FileNotFoundError(f"Overlay directory not found: {overlays_dir}")

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
        raise FileNotFoundError(f"No Kustomize overlays found in {overlays_dir}.")

    return overlays


def choose_overlay(overlays):
    print("Available overlays:")
    for index, overlay in enumerate(overlays, start=1):
        print(f"  {index}. {overlay.name}")

    while True:
        try:
            selection = input("Select an overlay by number: ").strip()
        except (EOFError, KeyboardInterrupt):
            raise RuntimeError("Overlay selection cancelled.") from None

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

    build = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        text=True,
        check=True,
    )

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
        subprocess.run(
            apply_command,
            input="\n---\n".join(manifests),
            text=True,
            check=True,
        )


def main(argv: Sequence[str] | None = None) -> None:
    parser = create_parser()
    args = parser.parse_args(argv)
    validate_secret_args(args, parser)

    k8s_dir = Path(__file__).resolve().parent.parent
    manifests_dir = k8s_dir / "manifests"
    overlays = find_overlays(manifests_dir / "overlays")
    if args.overlay is not None:
        selected_overlay = next(
            (overlay for overlay in overlays if overlay.name == args.overlay),
            None,
        )
        if selected_overlay is None:
            parser.error(
                f"unknown overlay {args.overlay!r}; available overlays: "
                + ", ".join(overlay.name for overlay in overlays)
            )
    elif args.non_interactive:
        if len(overlays) != 1:
            parser.error(
                "--non-interactive requires --overlay when multiple overlays are available"
            )
        selected_overlay = overlays[0]
    else:
        selected_overlay = choose_overlay(overlays)

    # Phase 1: Install external infrastructure: KEDA + sealed secrets.
    apply_infrastructure(manifests_dir / "infrastructure")

    # The CRD must exist before we can create a ScaledObject.
    wait_for_crd("scaledobjects.keda.sh")
    wait_for_crd("sealedsecrets.bitnami.com")

    # Phase 2: Install the application overlay, which may contain custom resources.
    # Wait until the controller can serve its public certificate to kubeseal.
    run("kubectl", "rollout", "status", "deployment/sealed-secrets-controller",
        "--namespace", "kube-system", "--timeout=120s")
    
    secret_args = []
    for attribute, option, _ in SECRETS:
        value = getattr(args, attribute)
        if value is not None:
            secret_args.extend((f"--{option}", value))
    if args.non_interactive:
        secret_args.append("--non-interactive")

    secret_creation_status = create_sealed_secret(secret_args)
    if secret_creation_status != 0:
        # Hide the traceback from the user. Might be misleading and not helpful in this context.
        raise SystemExit(secret_creation_status)

    # We intentionally do not wait for the KEDA operator to be ready.
    # Kubernetes can create the Custom Resources as soon as its CRD exists.
    # Once controllers start, it will discover and reconcile the existing resource.
    run("kubectl", "apply", "-k", str(selected_overlay))

    print("Deployment completed successfully.")


if __name__ == "__main__":
    main()