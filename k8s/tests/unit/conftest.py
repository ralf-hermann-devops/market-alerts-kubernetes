"""Isolate script imports and prevent unit tests from touching a real cluster."""

import getpass
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

K8S_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def forbid_external_interactions(monkeypatch):
    for target, name in (
        (subprocess, "run"),
        (getpass, "getpass"),
    ):
        monkeypatch.setattr(target, name, Mock(side_effect=AssertionError(name)))
    monkeypatch.setattr("builtins.input", Mock(side_effect=AssertionError("input")))


@pytest.fixture
def scripts(monkeypatch):
    def load(name, relative_path):
        spec = importlib.util.spec_from_file_location(name, K8S_ROOT / relative_path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    return SimpleNamespace(
        args=load("sealed_secrets_cli_args", "bootstrapping/sealed_secrets_cli_args.py"),
        secrets=load("create_sealed_secret", "bootstrapping/create_sealed_secret.py"),
        bootstrap=load("bootstrap_kubernetes_resources", "bootstrapping/bootstrap_kubernetes_resources.py"),
        images=load("cluster_image_loading", "bootstrapping/minikube_kind/cluster_image_loading.py"),
        kind=load("kind_build_and_load_images", "bootstrapping/minikube_kind/kind_build_and_load_images.py"),
        minikube=load("minikube_build_and_load_images", "bootstrapping/minikube_kind/minikube_build_and_load_images.py"),
        passthrough=load("passthrough_smoke", "tests/smoke_tests/simple_passthrough/run.py"),
        workloads=load("workload_smoke", "tests/smoke_tests/workload_controllers_started/run.py"),
    )


@pytest.fixture
def secret_args():
    # Synthetic values exercise Unicode, whitespace, and YAML/shell metacharacters.
    return [
        "--webhook-secret", "test-webhook-ü\nvalue",
        "--redis-password", "test-redis: #value",
        "--postgres-password", "test-postgres $(literal)",
    ]
