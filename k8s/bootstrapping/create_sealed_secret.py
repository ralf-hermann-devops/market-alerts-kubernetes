from __future__ import annotations

import base64
import getpass
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from cli_args import SECRETS, create_parser, validate_secret_args


"""
Because secrets should not be stored in git, someone will have to pass the value for 
passwords and other secrets to the cluster manually. The script accepts secret values
as command-line arguments or prompts for any values not provided. It creates a
SealedSecret manifest that can be applied to the cluster and safely stored in git.
The SealedSecret can only be decrypted by the Sealed Secrets controller running in
the target cluster.
"""


def collect_secret_values(provided_secrets: dict[str, str | None]) -> dict[str, str]:
    secret_values: dict[str, str] = {}
    for argument, key, prompt in SECRETS:
        value = provided_secrets[argument]
        if value is None:
            while not (value := getpass.getpass(f"{prompt}: ")):
                print("The value cannot be empty.")
        secret_values[key] = value
    return secret_values


def archive_existing_output(output_path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    archived_path = output_path.with_name(
        f"{output_path.stem}_retried_at_{timestamp}-{output_path.suffix}"
    )
    output_path.replace(archived_path)
    return archived_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = create_parser("Create a SealedSecret manifest.")
    args = parser.parse_args(argv)
    validate_secret_args(args, parser)
    provided_secrets = {argument: getattr(args, argument) for argument, _, _ in SECRETS}

    script_path = Path(__file__).resolve()
    k8s_dir = script_path.parent.parent
    output_path = (
        k8s_dir
        / "manifests"
        / "base"
        / "apps"
        / "trading-alerts-sealedsecret.yaml"
    )

    for executable in ("kubectl", "kubeseal"):
        if shutil.which(executable) is None:
            print(f"Required command not found on PATH: {executable}", file=sys.stderr)
            return 1

    # Fetch the Sealed Secrets public certificate from the cluster
    # Use it as a temporary file later to seal the secret values and create a SealedSecret manifest
    try:
        certificate = subprocess.run(
            [
                "kubeseal",
                "--fetch-cert",
                "--controller-name",
                "sealed-secrets-controller",
                "--controller-namespace",
                "kube-system",
            ],
            text=True,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as error:
        message = error.stderr.strip() or "The command failed without diagnostic output."
        print(
            "Could not fetch the Sealed Secrets public certificate from the cluster. "
            "Check that kubectl is connected to the target cluster and that the "
            f"controller is running in kube-system.\n{message}",
            file=sys.stderr,
        )
        return error.returncode or 1
    


    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        print(f"Could not create output directory {output_path.parent}: {error}", file=sys.stderr)
        return 1
    
    print(f"SealedSecret YAML will be written there: {output_path.parent}")

    # Check if the output file already exists and prompt the user for confirmation to replace it
    if output_path.exists():
        if not args.non_interactive:
            answer = input(f"{output_path} already exists. Replace it? [y/N] ").strip().lower()
            if answer not in {"y", "yes"}:
                print("No file was changed.")
                return 0

    secret_values = collect_secret_values(provided_secrets)

    # Encode the secret values in base64 and create a Kubernetes Secret manifest
    encoded_data = "\n".join(
        f"  {key}: {base64.b64encode(value.encode('utf-8')).decode('ascii')}"
        for key, value in secret_values.items()
    )
    secret_manifest = (
        "apiVersion: v1\n"
        "kind: Secret\n"
        "metadata:\n"
        "  name: trading-alerts-secrets\n"
        "  namespace: trading-alerts\n"
        "type: Opaque\n"
        "data:\n"
        f"{encoded_data}\n"
    )

    certificate_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            suffix=".pem",
            delete=False,   # we will delete it manually after sealing the secret
        ) as certificate_file:
            certificate_file.write(certificate.stdout)
            certificate_path = Path(certificate_file.name)

        # run operations using the tmp certificate file to create a SealedSecret manifest
        # outside of tmpfile context manager to avoid accessing a blocked file on Windows
        created_secret = subprocess.run(
            ["kubectl", "create", "-f", "-", "--dry-run=client", "-o", "yaml"],
            input=secret_manifest,
            text=True,
            capture_output=True,
            check=True,
        )
        sealed_secret = subprocess.run(
            [
                "kubeseal",
                "--format",
                "yaml",
                "--scope",
                "strict",
                "--cert",
                str(certificate_path),
            ],
            input=created_secret.stdout,
            text=True,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as error:
        message = error.stderr.strip() or "The command failed without diagnostic output."
        print(f"Could not create the SealedSecret: {message}", file=sys.stderr)
        return error.returncode or 1
    finally:
        if certificate_path is not None:
            certificate_path.unlink(missing_ok=True)

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_file.write(sealed_secret.stdout)
            temporary_path = Path(temporary_file.name)

        if args.non_interactive and output_path.exists():
            archived_path = archive_existing_output(output_path)
            print(f"Existing SealedSecret archived at {archived_path}")

        temporary_path.replace(output_path)
    except OSError as error:
        print(
            "Could not archive the existing or write the new SealedSecret file: "
            f"{error}",
            file=sys.stderr,
        )
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        return 1

    print(f"SealedSecret written to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
