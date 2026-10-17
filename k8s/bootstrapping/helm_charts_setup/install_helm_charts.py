#!/usr/bin/env python3

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HelmChart:
    release_name: str
    chart: str
    version: str
    repository_name: str
    repository_url: str
    namespace: str
    crds_to_wait_for: tuple[str, ...] = ()
    take_ownership: bool = False
    values_file: Path | None = None
    install_arguments: tuple[str, ...] = ()


HELM_CHARTS = (
    HelmChart(
        release_name="keda",
        chart="kedacore/keda",
        version="2.18.0",
        repository_name="kedacore",
        repository_url="https://kedacore.github.io/charts",
        namespace="keda",
        crds_to_wait_for=("scaledobjects.keda.sh",),
        take_ownership=True,
    ),
    HelmChart(
        release_name="kube-prometheus-stack",
        chart="prometheus-community/kube-prometheus-stack",
        version="92.3.0",
        repository_name="prometheus-community",
        repository_url="https://prometheus-community.github.io/helm-charts",
        namespace="monitoring",
        crds_to_wait_for=("servicemonitors.monitoring.coreos.com",),
    ),
    HelmChart(
        release_name="headlamp",
        chart="headlamp/headlamp",
        version="0.45.0",
        repository_name="headlamp",
        repository_url="https://kubernetes-sigs.github.io/headlamp/",
        namespace="monitoring",
    ),
    HelmChart(
        release_name="cert-manager",
        chart="jetstack/cert-manager",
        version="1.19.1",
        repository_name="jetstack",
        repository_url="https://charts.jetstack.io",
        namespace="cert-manager",
        crds_to_wait_for=(
            "certificates.cert-manager.io",
            "issuers.cert-manager.io",
            "clusterissuers.cert-manager.io",
        ),
        install_arguments=("--set", "crds.enabled=true"),
    ),
    # Ingress controller
    HelmChart(
        release_name="traefik",
        chart="traefik/traefik",
        version="41.7.1",
        repository_name="traefik",
        repository_url="https://traefik.github.io/charts",
        namespace="traefik",
    )
)


def run(*command: str) -> None:
    """Run a command with a 120-second timeout and display successful output.

    Raise RuntimeError for a nonzero exit status. subprocess.TimeoutExpired and
    process startup errors propagate to the caller.
    """
    print(f"$ {' '.join(command)}")
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=120)
    except subprocess.TimeoutExpired as e:
        print("Helm install command timed out")
        raise e

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

    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)


def install_helm_charts() -> None:
    """Install or upgrade configured Helm releases and await required CRDs.

    Update chart repositories and create release namespaces as needed. Each
    configured CRD must become established within 120 seconds. Relative values
    file paths are resolved from the current working directory.

    Raise ValueError for conflicting URLs under one repository name. Command
    failures raise RuntimeError; command timeouts and startup errors propagate.
    """
    # Register each repository once and reject conflicting URLs for a shared name.
    repositories: dict[str, str] = {}
    for helm_chart in HELM_CHARTS:
        previous_url = repositories.setdefault(
            helm_chart.repository_name,
            helm_chart.repository_url,
        )
        if previous_url != helm_chart.repository_url:
            raise ValueError(f"Helm repository {helm_chart.repository_name!r} has multiple URLs.")

    # Add all repositories
    for repository_name, repository_url in repositories.items():
        run("helm", "repo", "add", repository_name, repository_url, "--force-update")
        run("helm", "repo", "update", repository_name)

    for helm_chart in HELM_CHARTS:
        command = ["helm", "upgrade", "--install", helm_chart.release_name, helm_chart.chart,
            "--version", helm_chart.version,
            "--namespace", helm_chart.namespace,
            "--create-namespace"]
        if helm_chart.take_ownership:
            command.append("--take-ownership")
        if helm_chart.values_file is not None:
            command.extend(("--values", str(helm_chart.values_file)))
        command.extend(helm_chart.install_arguments)
        run(*command)


        for crd in helm_chart.crds_to_wait_for:
            run("kubectl", "wait", "--for=condition=Established",
                f"crd/{crd}",
                "--timeout=120s")


def main() -> None:
    """Install configured Helm charts, propagating installation errors."""
    install_helm_charts()


if __name__ == "__main__":
    main()
