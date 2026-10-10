import base64
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("non_interactive", [False, True])
def test_all_supplied_secrets_are_preserved(scripts, secret_args, non_interactive):
    parser = scripts.args.create_parser()
    args = parser.parse_args(secret_args + (["--non-interactive"] if non_interactive else []))
    scripts.args.validate_secret_args(args, parser)
    assert scripts.secrets.collect_secret_values(vars(args)) == {
        "webhook-secret": secret_args[1],
        "redis-password": secret_args[3],
        "postgres-password": secret_args[5],
    }


@pytest.mark.parametrize("missing_index", [0, 2, 4])
def test_non_interactive_rejects_each_missing_secret(scripts, secret_args, missing_index, capsys):
    missing = secret_args[missing_index]
    del secret_args[missing_index:missing_index + 2]
    parser = scripts.args.create_parser()
    with pytest.raises(SystemExit) as error:
        scripts.args.validate_secret_args(parser.parse_args(secret_args + ["--non-interactive"]), parser)
    assert error.value.code == 2
    assert missing in capsys.readouterr().err


@pytest.mark.parametrize("index", [1, 3, 5])
@pytest.mark.parametrize("non_interactive", [False, True])
def test_empty_secret_is_rejected(scripts, secret_args, index, non_interactive, capsys):
    secret_args[index] = ""
    parser = scripts.args.create_parser()
    with pytest.raises(SystemExit) as error:
        scripts.args.validate_secret_args(
            parser.parse_args(secret_args + (["--non-interactive"] if non_interactive else [])), parser
        )
    assert error.value.code == 2
    assert "secret values cannot be empty" in capsys.readouterr().err


def test_interactive_collection_only_prompts_for_missing_values(scripts, monkeypatch):
    prompt = Mock(side_effect=["", "test-redis", "test-postgres"])
    monkeypatch.setattr(scripts.secrets.getpass, "getpass", prompt)
    parser = scripts.args.create_parser()
    args = parser.parse_args(["--webhook-secret", "test-webhook"])
    scripts.args.validate_secret_args(args, parser)
    assert scripts.secrets.collect_secret_values(vars(args)) == {
        "webhook-secret": "test-webhook", "redis-password": "test-redis",
        "postgres-password": "test-postgres",
    }
    assert [call.args[0] for call in prompt.call_args_list] == [
        "Redis password: ", "Redis password: ", "PostgreSQL password: ",
    ]


@pytest.fixture
def sealing(scripts, monkeypatch, tmp_path):
    module = scripts.secrets
    monkeypatch.setattr(module, "__file__", str(tmp_path / "bootstrapping/create_sealed_secret.py"))
    monkeypatch.setattr(module.shutil, "which", lambda executable: f"/tools/{executable}")
    monkeypatch.setattr(module.tempfile, "tempdir", str(tmp_path))
    command = Mock(side_effect=[
        subprocess.CompletedProcess([], 0, stdout="test-public-certificate"),
        subprocess.CompletedProcess([], 0, stdout="normalized-secret"),
        subprocess.CompletedProcess([], 0, stdout="kind: SealedSecret\n"),
    ])
    monkeypatch.setattr(module.subprocess, "run", command)
    output = tmp_path / "manifests/base/apps/trading-alerts-sealedsecret.yaml"
    return module, command, output


@pytest.mark.parametrize("existing", [False, True])
def test_non_interactive_sealing_and_archive(sealing, secret_args, existing, capsys):
    module, command, output = sealing
    if existing:
        output.parent.mkdir(parents=True)
        output.write_text("previous encrypted manifest", encoding="utf-8")
    assert module.main(secret_args + ["--non-interactive"]) == 0
    assert output.read_text() == "kind: SealedSecret\n"
    archives = list(output.parent.glob("*_retried_at_*.yaml"))
    assert len(archives) == int(existing)
    if existing:
        assert archives[0].read_text() == "previous encrypted manifest"

    fetch, create, seal = command.call_args_list
    assert fetch.args[0] == [
        "kubeseal", "--fetch-cert", "--controller-name", "sealed-secrets-controller",
        "--controller-namespace", "kube-system",
    ]
    assert create.args[0] == ["kubectl", "create", "-f", "-", "--dry-run=client", "-o", "yaml"]
    manifest = create.kwargs["input"]
    metadata, data = manifest.split("\ndata:\n", 1)
    assert "kind: Secret\n" in metadata
    assert "  name: trading-alerts-secrets\n  namespace: trading-alerts\n" in metadata
    decoded = {
        key: base64.b64decode(value).decode("utf-8")
        for key, value in (line.strip().split(": ", 1) for line in data.splitlines())
    }
    assert decoded == dict(zip(["webhook-secret", "redis-password", "postgres-password"], secret_args[1::2]))
    assert seal.args[0][:-1] == ["kubeseal", "--format", "yaml", "--scope", "strict", "--cert"]
    assert seal.kwargs["input"] == "normalized-secret"
    assert not Path(seal.args[0][-1]).exists()
    assert not list(output.parent.glob("*.tmp"))
    for call in command.call_args_list:
        assert call.kwargs["check"] is True
    captured = capsys.readouterr()
    for value in secret_args[1::2]:
        assert value not in captured.out + captured.err


def test_archive_uses_utc_timestamp_and_moves_contents(sealing, monkeypatch):
    module, _, output = sealing
    output.parent.mkdir(parents=True)
    output.write_text("old encrypted data")
    clock = Mock()
    clock.now.return_value = datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=timezone.utc)
    monkeypatch.setattr(module, "datetime", clock)
    archived = module.archive_existing_output(output)
    clock.now.assert_called_once_with(timezone.utc)
    assert "20260102T030405.678901Z" in archived.name
    assert archived.parent == output.parent
    assert archived.suffix == ".yaml"
    assert archived.read_text() == "old encrypted data"
    assert not output.exists()


@pytest.mark.parametrize("answer,replace", [("", False), ("no", False), ("yes", True), (" Y ", True)])
def test_interactive_replacement(sealing, secret_args, monkeypatch, answer, replace):
    module, command, output = sealing
    output.parent.mkdir(parents=True)
    output.write_text("previous encrypted manifest")
    monkeypatch.setattr("builtins.input", Mock(return_value=answer))
    assert module.main(secret_args) == 0
    assert output.read_text() == ("kind: SealedSecret\n" if replace else "previous encrypted manifest")
    assert command.call_count == (3 if replace else 1)
    assert not list(output.parent.glob("*_retried_at_*.yaml"))


@pytest.mark.parametrize("executable", ["kubectl", "kubeseal"])
def test_missing_tool_does_not_touch_output(sealing, secret_args, monkeypatch, executable, capsys):
    module, command, output = sealing
    monkeypatch.setattr(module.shutil, "which", lambda name: None if name == executable else "/tools/ok")
    assert module.main(secret_args + ["--non-interactive"]) == 1
    command.assert_not_called()
    assert not output.exists()
    assert executable in capsys.readouterr().err


@pytest.mark.parametrize("failed_stage", [0, 1, 2])
@pytest.mark.parametrize("diagnostic", ["test failure", ""])
def test_failed_command_preserves_existing_secret_and_cleans_certificate(
    sealing, secret_args, failed_stage, diagnostic, capsys
):
    module, command, output = sealing
    output.parent.mkdir(parents=True)
    output.write_text("previous encrypted manifest")
    command.side_effect = [
        subprocess.CompletedProcess([], 0, stdout="test-certificate")
    ] * failed_stage + [subprocess.CalledProcessError(7, ["test-command"], stderr=diagnostic)]
    assert module.main(secret_args + ["--non-interactive"]) == 7
    assert command.call_count == failed_stage + 1
    assert output.read_text() == "previous encrypted manifest"
    assert list(output.parent.iterdir()) == [output]
    assert not list(output.parents[3].glob("*.pem"))
    assert (diagnostic or "without diagnostic output") in capsys.readouterr().err


def test_archive_failure_preserves_previous_secret_and_removes_staged_output(
    sealing, secret_args, monkeypatch, capsys
):
    module, _, output = sealing
    output.parent.mkdir(parents=True)
    output.write_text("previous encrypted manifest")
    monkeypatch.setattr(module, "archive_existing_output", Mock(side_effect=OSError("archive denied")))
    assert module.main(secret_args + ["--non-interactive"]) == 1
    assert output.read_text() == "previous encrypted manifest"
    assert list(output.parent.iterdir()) == [output]
    assert "archive denied" in capsys.readouterr().err


def test_invalid_non_interactive_arguments_fail_before_external_commands(sealing):
    module, command, output = sealing
    with pytest.raises(SystemExit) as error:
        module.main(["--non-interactive"])
    assert error.value.code == 2
    command.assert_not_called()
    assert not output.exists()


def test_certificate_is_available_while_sealing_and_removed_afterward(sealing, secret_args):
    module, command, output = sealing
    certificates = []

    def run(args, **kwargs):
        if "--fetch-cert" in args:
            result = "test-public-certificate"
        elif args[0] == "kubectl":
            result = kwargs["input"]
        else:
            certificate = Path(args[args.index("--cert") + 1])
            assert certificate.read_text() == "test-public-certificate"
            certificates.append(certificate)
            result = "kind: SealedSecret\n"
        return subprocess.CompletedProcess(args, 0, stdout=result)

    command.side_effect = run
    assert module.main(secret_args + ["--non-interactive"]) == 0
    assert len(certificates) == 1
    assert not certificates[0].exists()
    assert output.read_text() == "kind: SealedSecret\n"


def test_failed_publication_retains_archived_secret(sealing, secret_args, monkeypatch, capsys):
    module, _, output = sealing
    output.parent.mkdir(parents=True)
    output.write_text("previous encrypted manifest")
    original_replace = Path.replace

    def replace(path, target):
        if path.suffix == ".tmp":
            raise OSError("publication denied")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", replace)
    assert module.main(secret_args + ["--non-interactive"]) == 1
    archives = list(output.parent.glob("*_retried_at_*.yaml"))
    assert len(archives) == 1
    assert archives[0].read_text() == "previous encrypted manifest"
    assert not list(output.parent.glob("*.tmp"))
    assert "publication denied" in capsys.readouterr().err
