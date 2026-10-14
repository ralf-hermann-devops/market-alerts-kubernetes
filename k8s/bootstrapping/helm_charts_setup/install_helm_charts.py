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
    )
)


def run(*command: str) -> None:
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
    """Install configured Helm charts and wait for their required CRDs."""
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
        run(*command)


        for crd in helm_chart.crds_to_wait_for:
            run("kubectl", "wait", "--for=condition=Established",
                f"crd/{crd}",
                "--timeout=120s")


def main() -> None:
    install_helm_charts()


if __name__ == "__main__":
    main()
