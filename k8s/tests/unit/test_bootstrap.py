import subprocess
from pathlib import Path
from unittest.mock import Mock, call

import pytest


@pytest.mark.parametrize("directory_exists", [False, True])
def test_find_overlays_rejects_missing_or_empty_directory(scripts, tmp_path, directory_exists):
    directory = tmp_path / "overlays"
    if directory_exists:
        directory.mkdir()
        (directory / "not-an-overlay").mkdir()
    with pytest.raises(FileNotFoundError):
        scripts.bootstrap.find_overlays(directory)


def test_find_overlays_accepts_kustomizations_and_sorts_case_insensitively(scripts, tmp_path):
    names = ["zulu", "Alpha", "beta", "DEV", "gamma"]
    filenames = ["kustomization.yaml", "kustomization.yml", "Kustomization", "Kustomization.yaml", "Kustomization.yml"]
    for name, filename in zip(names, filenames):
        overlay = tmp_path / name
        overlay.mkdir()
        (overlay / filename).write_text("resources: []\n")
    (tmp_path / "ordinary-file").touch()
    (tmp_path / "invalid/kustomization.yaml").mkdir(parents=True)
    assert [path.name for path in scripts.bootstrap.find_overlays(tmp_path)] == [
        "Alpha", "beta", "DEV", "gamma", "zulu",
    ]


@pytest.mark.parametrize("exception", [EOFError, KeyboardInterrupt])
def test_cancelled_overlay_selection_raises_clear_error(scripts, monkeypatch, exception):
    monkeypatch.setattr("builtins.input", Mock(side_effect=exception))
    with pytest.raises(RuntimeError, match="Overlay selection cancelled"):
        scripts.bootstrap.choose_overlay([Path("dev")])


@pytest.fixture
def bootstrap(scripts, monkeypatch, tmp_path):
    module = scripts.bootstrap
    monkeypatch.setattr(module, "__file__", str(tmp_path / "bootstrapping/bootstrap_kubernetes_resources.py"))
    overlays = tmp_path / "manifests/overlays"
    (overlays / "dev").mkdir(parents=True)
    (overlays / "dev/kustomization.yaml").write_text("resources: []\n")
    operations = Mock()
    for name in ("apply_infrastructure", "wait_for_crd", "run", "create_sealed_secret"):
        monkeypatch.setattr(module, name, getattr(operations, name))
    operations.create_sealed_secret.return_value = 0
    return module, operations, overlays


@pytest.mark.parametrize("explicit", [False, True])
def test_bootstrap_waits_before_sealing_and_applying_overlay(bootstrap, secret_args, explicit):
    module, operations, overlays = bootstrap
    args = secret_args + ["--non-interactive"]
    if explicit:
        (overlays / "prod").mkdir()
        (overlays / "prod/kustomization.yaml").touch()
        args += ["--overlay", "dev"]
    module.main(args)
    assert operations.mock_calls == [
        call.apply_infrastructure(overlays.parent / "infrastructure"),
        call.wait_for_crd("scaledobjects.keda.sh"),
        call.wait_for_crd("sealedsecrets.bitnami.com"),
        call.run("kubectl", "rollout", "status", "deployment/sealed-secrets-controller",
                 "--namespace", "kube-system", "--timeout=120s"),
        call.create_sealed_secret(secret_args + ["--non-interactive"]),
        call.run("kubectl", "apply", "-k", str(overlays / "dev")),
    ]


@pytest.mark.parametrize("selection", [None, "missing", "../dev", "DEV"])
def test_invalid_or_ambiguous_overlay_fails_before_deployment(bootstrap, secret_args, selection, capsys):
    module, operations, overlays = bootstrap
    (overlays / "prod").mkdir()
    (overlays / "prod/kustomization.yaml").touch()
    args = secret_args + ["--non-interactive"]
    if selection is not None:
        args += ["--overlay", selection]
    with pytest.raises(SystemExit) as error:
        module.main(args)
    assert error.value.code == 2
    assert operations.mock_calls == []
    assert ("requires --overlay" if selection is None else "unknown overlay") in capsys.readouterr().err


def test_interactive_bootstrap_forwards_only_provided_secrets(bootstrap, monkeypatch):
    module, operations, _ = bootstrap
    monkeypatch.setattr("builtins.input", Mock(return_value="1"))
    module.main(["--redis-password", "synthetic-redis"])
    operations.create_sealed_secret.assert_called_once_with(["--redis-password", "synthetic-redis"])


def test_secret_creation_failure_prevents_overlay_application(bootstrap, secret_args):
    module, operations, _ = bootstrap
    operations.create_sealed_secret.return_value = 7
    with pytest.raises(SystemExit) as error:
        module.main(secret_args + ["--non-interactive"])
    assert error.value.code == 7
    assert operations.run.call_count == 1
    assert operations.run.call_args.args[1:3] == ("rollout", "status")


@pytest.mark.parametrize("stage", ["apply_infrastructure", "wait_for_crd", "run"])
def test_failed_prerequisite_stops_before_secret_creation(bootstrap, secret_args, stage):
    module, operations, _ = bootstrap
    failure = subprocess.CalledProcessError(4, ["kubectl"])
    getattr(operations, stage).side_effect = failure
    with pytest.raises(subprocess.CalledProcessError) as error:
        module.main(secret_args + ["--non-interactive"])
    assert error.value is failure
    operations.create_sealed_secret.assert_not_called()
    assert not any(c.args[:3] == ("kubectl", "apply", "-k") for c in operations.run.call_args_list)


def test_run_checks_subprocess_status(scripts, monkeypatch):
    command = Mock(side_effect=subprocess.CalledProcessError(6, ["kubectl", "apply"]))
    monkeypatch.setattr(scripts.bootstrap.subprocess, "run", command)
    with pytest.raises(subprocess.CalledProcessError):
        scripts.bootstrap.run("kubectl", "apply")
    command.assert_called_once_with(("kubectl", "apply"), check=True)


@pytest.mark.parametrize("failure_stage", [None, 0, 1, 2])
def test_infrastructure_applies_crds_first_and_stops_on_failure(scripts, monkeypatch, tmp_path, failure_stage):
    crd = "apiVersion: apiextensions.k8s.io/v1\nkind: CustomResourceDefinition\nmetadata:\n  name: tests.example.com\n"
    resource = "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: example\n"
    results = [subprocess.CompletedProcess([], 0, stdout=resource + "---\n" + crd), None, None]
    if failure_stage is not None:
        results[failure_stage] = subprocess.CalledProcessError(5, ["kubectl"], stderr="test failure")
    command = Mock(side_effect=results)
    monkeypatch.setattr(scripts.bootstrap.subprocess, "run", command)
    if failure_stage is None:
        scripts.bootstrap.apply_infrastructure(tmp_path)
    else:
        with pytest.raises(subprocess.CalledProcessError):
            scripts.bootstrap.apply_infrastructure(tmp_path)
    expected = [
        call(["kubectl", "kustomize", "--enable-helm", str(tmp_path)], stdout=subprocess.PIPE, text=True, check=True),
        call(["kubectl", "apply", "--server-side", "--force-conflicts", "-f", "-"], input="\n" + crd, text=True, check=True),
        call(["kubectl", "apply", "-f", "-"], input=resource, text=True, check=True),
    ]
    assert command.call_args_list == expected[:None if failure_stage is None else failure_stage + 1]
