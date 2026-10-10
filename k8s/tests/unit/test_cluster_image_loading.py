import json
import subprocess
import sys
from unittest.mock import Mock, call

import pytest


@pytest.mark.parametrize("answers,expected", [
    (["yes", "all"], ["alpha", "beta", "gamma"]),
    ([" Y ", " ALL "], ["alpha", "beta", "gamma"]),
    (["yes", "3, 1, 3, 2"], ["gamma", "alpha", "beta"]),
    (["maybe", "y", "", "abc", "0", "-1", "4", "1,", "2"], ["beta"]),
    (["n"], None),
    ([" NO "], None),
])
def test_cluster_selection_validation_and_deduplication(scripts, monkeypatch, answers, expected):
    prompt = Mock(side_effect=answers)
    monkeypatch.setattr("builtins.input", prompt)
    assert scripts.images.select_existing_clusters("kind", ["alpha", "beta", "gamma"]) == expected
    assert prompt.call_count == len(answers)


def test_no_existing_clusters_does_not_prompt(scripts):
    assert scripts.images.select_existing_clusters("kind", []) is None


@pytest.mark.parametrize("clusters,hint,answers,expected", [
    ([], " new ", [], (["new"], True)),
    ([], None, ["", "   ", " new "], (["new"], True)),
    (["old"], "ignored", ["y", "1"], (["old"], False)),
    (["old"], "old", ["n", "maybe", "yes"], (["old"], False)),
    (["old"], "old", ["n", "no", "new"], (["new"], True)),
])
def test_new_cluster_naming_and_existing_name_collision(scripts, monkeypatch, clusters, hint, answers, expected):
    prompt = Mock(side_effect=answers)
    monkeypatch.setattr("builtins.input", prompt)
    assert scripts.images.prompt_for_runs_cluster_name("kind", clusters, hint) == expected
    assert prompt.call_count == len(answers)


@pytest.mark.parametrize("capture", [False, True])
def test_commands_use_project_root_and_checked_exit_status(scripts, monkeypatch, tmp_path, capture):
    command = Mock(return_value=subprocess.CompletedProcess([], 0, stdout="alpha\n"))
    monkeypatch.setattr(scripts.images.subprocess, "run", command)
    monkeypatch.chdir(tmp_path)
    args = ["kind", "get", "clusters"]
    expected = dict(cwd=scripts.images.PROJECT_ROOT, check=True)
    if capture:
        assert scripts.images.output(args) == "alpha\n"
        expected.update(stdout=subprocess.PIPE, text=True)
    else:
        assert scripts.images.run(args) is None
    command.assert_called_once_with(args, **expected)
    assert (scripts.images.PROJECT_ROOT / "Dockercompose.yaml").is_file()


def test_build_images_targets_only_application_services(scripts, monkeypatch):
    command = Mock()
    monkeypatch.setattr(scripts.images, "run", command)
    scripts.images.build_images()
    command.assert_called_once_with([
        "docker", "compose", "-f", "Dockercompose.yaml", "build", "api", "worker", "fetcher",
    ])


@pytest.mark.parametrize("failure,status,message", [
    (None, 0, ""),
    (FileNotFoundError(2, "not found", "kind"), 1, "Required command not found: kind"),
    (subprocess.CalledProcessError(7, ["docker", "compose", "build"]), 7, "docker compose build"),
])
def test_command_failures_have_actionable_exit_status(scripts, failure, status, message, capsys):
    action = Mock(side_effect=failure)
    assert scripts.images.run_with_error_handling(action) == status
    action.assert_called_once_with()
    assert message in capsys.readouterr().err


@pytest.mark.parametrize("profiles,expected", [
    ({"valid": []}, []),
    ({"valid": [{"Name": "alpha"}, {"Name": "beta"}], "invalid": [{"Name": "ignored"}]}, ["alpha", "beta"]),
])
def test_minikube_profiles(scripts, monkeypatch, profiles, expected):
    output = Mock(return_value=json.dumps(profiles))
    monkeypatch.setattr(scripts.minikube, "output", output)
    assert scripts.minikube.get_profiles() == expected
    output.assert_called_once_with(["minikube", "profile", "list", "-o", "json"])


@pytest.mark.parametrize("profiles", [[], None, {}, {"valid": None}, {"valid": {}},
    {"valid": [None]}, {"valid": [{}]}, {"valid": [{"Name": 42}]}])
def test_minikube_rejects_malformed_profile_structure(scripts, monkeypatch, profiles):
    monkeypatch.setattr(scripts.minikube, "output", Mock(return_value=json.dumps(profiles)))
    with pytest.raises(TypeError):
        scripts.minikube.get_profiles()


def test_minikube_rejects_invalid_json(scripts, monkeypatch):
    monkeypatch.setattr(scripts.minikube, "output", Mock(return_value="not JSON"))
    with pytest.raises(json.JSONDecodeError):
        scripts.minikube.get_profiles()


@pytest.mark.parametrize("platform", ["kind", "minikube"])
@pytest.mark.parametrize("create", [False, True])
def test_image_loading_builds_once_and_targets_selected_clusters(scripts, monkeypatch, platform, create):
    module = getattr(scripts, platform)
    selected = ["new"] if create else ["beta", "alpha"]
    operations = Mock()
    operations.output.return_value = " alpha \n\n beta\n" if platform == "kind" else json.dumps({
        "valid": [{"Name": "alpha"}, {"Name": "beta"}],
    })
    operations.prompt_for_runs_cluster_name.return_value = (selected, create)
    for name in ("output", "prompt_for_runs_cluster_name", "build_images", "run"):
        monkeypatch.setattr(module, name, getattr(operations, name))
    monkeypatch.setattr(sys, "argv", ["image-loader", "--name", "new"])
    assert module.main() == 0
    discovery = ["kind", "get", "clusters"] if platform == "kind" else ["minikube", "profile", "list", "-o", "json"]
    expected = [
        call.output(discovery),
        call.prompt_for_runs_cluster_name("kind" if platform == "kind" else "Minikube", ["alpha", "beta"], "new"),
        call.build_images(),
    ]
    images = ["trading-api:dev", "trading-worker:dev", "trading-fetcher:dev"]
    for cluster in selected:
        if platform == "kind":
            if create:
                expected.append(call.run(["kind", "create", "cluster", "--name", cluster]))
            expected.append(call.run(["kind", "load", "docker-image", *images, "--name", cluster]))
        else:
            expected.append(call.run(["minikube", "start", "--profile", cluster]))
            expected.extend(call.run(["minikube", "--profile", cluster, "image", "load", image]) for image in images)
            expected.append(call.run(["minikube", "--profile", cluster, "image", "list"]))
    assert operations.mock_calls == expected


@pytest.mark.parametrize("platform", ["kind", "minikube"])
@pytest.mark.parametrize("stage", ["output", "build_images", "run"])
def test_loading_stops_on_first_failed_command(scripts, monkeypatch, platform, stage, capsys):
    module = getattr(scripts, platform)
    monkeypatch.setattr(sys, "argv", ["image-loader"])
    output = Mock(return_value="alpha\n" if platform == "kind" else '{"valid": [{"Name": "alpha"}]}')
    build = Mock()
    run = Mock()
    for name, mocked in (("output", output), ("build_images", build), ("run", run)):
        monkeypatch.setattr(module, name, mocked)
    monkeypatch.setattr(module, "prompt_for_runs_cluster_name", Mock(return_value=(["alpha", "beta"], False)))
    getattr(module, stage).side_effect = subprocess.CalledProcessError(9, ["test-command"])
    assert module.main() == 9
    if stage == "output":
        build.assert_not_called()
    assert run.call_count == (1 if stage == "run" else 0)
    assert "successfully" not in capsys.readouterr().out
