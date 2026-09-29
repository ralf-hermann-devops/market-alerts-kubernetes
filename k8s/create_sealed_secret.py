from __future__ import annotations

import base64
import getpass
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


"""
Because secrets should not be stored in git, someone will have to pass the value for 
passwords and other secrets to the cluster manually. The script will prompt for the
secret values encoded in base64 and create a SealedSecret manifest that can be applied
to the cluster and is safe to store in git. The SealedSecret can only be decrypted by
the Sealed Secrets controller running in the target cluster.
"""

def main() -> int:
    script_path = Path(__file__).resolve()
    k8s_dir = script_path.parent
    output_path = k8s_dir / "base" / "apps" / "trading-alerts-sealedsecret.yaml"

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
        answer = input(f"{output_path} already exists. Replace it? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("No file was changed.")
            return 0

    # Prompt the user for secret values, ensuring that they are not empty
    secret_values: dict[str, str] = {}
    for key, prompt in (
        ("webhook-secret", "TradingView webhook secret: "),
        ("redis-password", "Redis password: "),
        ("postgres-password", "PostgreSQL password: "),
    ):
        while not (value := getpass.getpass(prompt)):   # dont show input in console
            print("The value cannot be empty.")
        secret_values[key] = value

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

        temporary_path.replace(output_path)
    except OSError as error:
        print(f"Could not write the SealedSecret file: {error}", file=sys.stderr)
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        return 1

    print(f"SealedSecret written to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
