"""Test the changed smoke-test helpers without running their cluster checks."""

import subprocess
from unittest.mock import Mock, call

import pytest


@pytest.mark.parametrize("name", ["passthrough", "workloads"])
@pytest.mark.parametrize("capture", [False, True])
@pytest.mark.parametrize("stdout,stderr", [("  ready\n", "test warning\n"), ("", "")])
def test_kubectl_captures_or_displays_output(scripts, monkeypatch, capsys, name, capture, stdout, stderr):
    module = getattr(scripts, name)
    command = Mock(return_value=subprocess.CompletedProcess([], 0, stdout=stdout, stderr=stderr))
    monkeypatch.setattr(module.subprocess, "run", command)
    result = module.kubectl("get", "pods", capture_output=capture)
    command.assert_called_once_with(["kubectl", "get", "pods"], check=True, capture_output=True, text=True)
    assert result == (stdout.strip() if capture else "")
    captured = capsys.readouterr()
    assert captured.out == "$ kubectl get pods\n" + ("" if capture else stdout)
    assert captured.err == ("" if capture else stderr)


@pytest.mark.parametrize("name", ["passthrough", "workloads"])
@pytest.mark.parametrize("stdout,stderr", [("partial result\n", "failed\n"), (None, None), ("", "")])
def test_kubectl_prints_diagnostics_and_reraises_original_failure(scripts, monkeypatch, capsys, name, stdout, stderr):
    module = getattr(scripts, name)
    failure = subprocess.CalledProcessError(8, ["kubectl", "get", "pods"], output=stdout, stderr=stderr)
    monkeypatch.setattr(module.subprocess, "run", Mock(side_effect=failure))
    with pytest.raises(subprocess.CalledProcessError) as error:
        module.kubectl("get", "pods", capture_output=True)
    assert error.value is failure
    captured = capsys.readouterr()
    assert captured.err == (f"stdout:\n{stdout}" if stdout else "") + (f"stderr:\n{stderr}" if stderr else "")


def test_workload_checks_wait_for_each_application_controller(scripts, monkeypatch, capsys):
    command = Mock(return_value="")
    monkeypatch.setattr(scripts.workloads, "kubectl", command)
    assert scripts.workloads.main() == 0
    assert command.call_args_list == [
        call("rollout", "status", resource, "--namespace", "trading-alerts", "--timeout=120s")
        for resource in ("deployment/api", "deployment/worker", "deployment/redis", "statefulset/postgres")
    ]
    assert "All application components started successfully." in capsys.readouterr().out


@pytest.mark.parametrize("failure,message", [
    (FileNotFoundError(2, "not found", "kubectl"), "Required command not found: kubectl"),
    (RuntimeError("controller unavailable"), "controller unavailable"),
    (TimeoutError("readiness timed out"), "readiness timed out"),
])
def test_workload_failure_stops_remaining_checks(scripts, monkeypatch, capsys, failure, message):
    command = Mock(side_effect=["", failure])
    monkeypatch.setattr(scripts.workloads, "kubectl", command)
    assert scripts.workloads.main() == 1
    assert command.call_count == 2
    captured = capsys.readouterr()
    assert message in captured.err
    assert "All application components started successfully." not in captured.out


def test_failed_rollout_cannot_report_success(scripts, monkeypatch, capsys):
    failure = subprocess.CalledProcessError(1, ["kubectl", "rollout", "status"])
    command = Mock(side_effect=failure)
    monkeypatch.setattr(scripts.workloads.subprocess, "run", command)
    with pytest.raises(subprocess.CalledProcessError) as error:
        scripts.workloads.main()
    assert error.value is failure
    command.assert_called_once()
    assert "All application components started successfully." not in capsys.readouterr().out
