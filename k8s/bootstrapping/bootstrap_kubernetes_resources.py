#!/usr/bin/env python3

import argparse
import subprocess
import sys
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
    """Build the CLI parser for secret values and overlay selection."""
    parser = create_common_parser(
        "Bootstrap Kubernetes infrastructure and an application overlay."
    )
    parser.add_argument(
        "--overlay",
        help="Overlay directory name to apply (required for non-interactive mode if ambiguous)",
    )
    return parser


def run(*command: str,
        input_text: str | None = None,
        print_stdout: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a command, display its output, and raise a useful error on failure."""
    print(f"$ {' '.join(command)}")
    result = subprocess.run(
        command,
        input=input_text,
        capture_output=True,
        text=True,
    )

    if result.returncode:
        details = "\n".join(
            output.strip()
            for output in (result.stdout, result.stderr)
            if output.strip()
        )
        raise RuntimeError(
            f"{' '.join(command)} failed with exit code "
            f"{result.returncode}:\n{details or 'Command returned no output.'}"
        )

    if print_stdout and result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result


def wait_for_crd(crd, timeout=120):
    """Wait up to timeout seconds for a CRD to become established."""
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
    """Return overlay paths sorted by name, or raise FileNotFoundError if absent."""
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
    """Prompt for an overlay path, raising RuntimeError if selection is cancelled."""
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


def apply_infrastructure(infrastructure_dir, kustomize_args=[]):
    """Render infrastructure kustomize args and apply all rendered resources."""
    build = run("kubectl", "kustomize", *kustomize_args, str(infrastructure_dir),
        print_stdout=False,
    )

    # API-server managedFields tracks ownership without the oversized last-applied annotation.
    # Use `kubectl get <RESSOURCE> <NAME> -n keda -o yaml --show-managed-fields`
    # to see the fields managed by the API server.
    # Managed ressources include the deployments
    # - keda-operator
    # - keda-admission-webhooks
    # - keda-operator-metrics-apiserver
    # and validatingwebhookconfiguration
    # - keda-admission
    run("kubectl", "apply", "--server-side", "--force-conflicts", "-f", "-",
        input_text=build.stdout,
    )


def main(argv: Sequence[str] | None = None) -> None:
    """Parse CLI options, install infrastructure, seal secrets, and deploy an overlay."""
    parser = create_parser()
    args = parser.parse_args(argv)
    validate_secret_args(args, parser)

    k8s_dir = Path(__file__).resolve().parents[1]
    manifests_dir = k8s_dir / "manifests"
    overlays = find_overlays(manifests_dir / "overlays")
    if args.overlay is not None:
        selected_overlay = None
        for overlay in overlays:
            if overlay.name == args.overlay:
                selected_overlay = overlay
                break
        if selected_overlay is None:
            parser.error(
                f"unknown overlay {args.overlay!r}; available overlays: "
                + ", ".join(overlay.name for overlay in overlays)
            )
    elif args.non_interactive:
        if len(overlays) != 1:
            parser.error("--non-interactive requires --overlay when multiple overlays are available")
        selected_overlay = overlays[0]
    else:
        selected_overlay = choose_overlay(overlays)

    # Phase 1: Install shared external infrastructure: KEDA
    apply_infrastructure(manifests_dir / "infrastructure", kustomize_args=["--enable-helm"])

    

    # Phase 2: Special overlay-specific steps before overlay is getting applied.
    # One thing to do is install the overlay's secrets and secret solution
    # The on-premise overlay needs the sealed-secrets controller to be installed first
    # so the bootstrap script can create the sealed secret for the overlay.
    if selected_overlay.name == "on-premise":
        apply_infrastructure(selected_overlay / "sealed_secrets")

        # Wait until the controller can serve its public certificate to kubeseal.
        wait_for_crd("sealedsecrets.bitnami.com")
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
    elif selected_overlay.name == "aws":
        raise NotImplementedError("AWS overlay is not yet supported in this script.")
    else:
        raise NotImplementedError(f"Overlay {selected_overlay.name!r} is not supported in this script.")


    # We intentionally do not wait for the KEDA operator to be ready.
    # Kubernetes can create the Custom Resources as soon as its CRD exists.
    # Once controllers start, it will discover and reconcile the existing resource.
    run("kubectl", "apply", "-k", str(selected_overlay))

    print("Deployment completed successfully.")


if __name__ == "__main__":
    main()