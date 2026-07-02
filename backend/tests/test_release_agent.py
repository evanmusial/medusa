import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


def load_release_agent():
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("medusa_release_agent", root / "scripts" / "medusa-release-agent.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout.strip()


def commit_all(repo: Path, message: str) -> str:
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-m", message)
    return run_git(repo, "rev-parse", "HEAD")


def write_haproxy_tls_placeholders(repo: Path) -> None:
    cert_dir = repo / "data" / "haproxy"
    cert_dir.mkdir(parents=True)
    (cert_dir / "fullchain.pem").write_text("certificate\n")
    (cert_dir / "privatekey.pem").write_text("private key\n")


def test_release_agent_probes_origin_port_when_public_port_is_standard(monkeypatch, tmp_path):
    agent = load_release_agent()
    for key in (
        "MEDUSA_PUBLIC_HOST",
        "MEDUSA_PUBLIC_PORT",
        "MEDUSA_HAPROXY_PORT",
        "MEDUSA_RELEASE_HEALTHCHECK_PORT",
        "MEDUSA_RELEASE_HEALTHCHECK_IP",
        "MEDUSA_BIND_IP",
        "MEDUSA_BIND_IPV6",
    ):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "MEDUSA_PUBLIC_HOST=medusa.evan.engineer",
                "MEDUSA_PUBLIC_PORT=443",
                "MEDUSA_HAPROXY_PORT=3737",
                "MEDUSA_BIND_IP=23.227.185.85",
            ]
        )
        + "\n"
    )

    command, url = agent.health_url(tmp_path)

    assert url == "https://medusa.evan.engineer:3737/api/health"
    assert command == [
        "curl",
        "-kfsS",
        "--connect-timeout",
        "5",
        "--max-time",
        "10",
        "--resolve",
        "medusa.evan.engineer:3737:23.227.185.85",
        "https://medusa.evan.engineer:3737/api/health",
    ]


def test_release_agent_classifies_safe_dependency_and_risky_runtime_updates(tmp_path):
    agent = load_release_agent()
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init")
    run_git(repo, "config", "user.email", "test@example.invalid")
    run_git(repo, "config", "user.name", "Medusa Test")
    (repo / "backend").mkdir()
    (repo / "frontend").mkdir()
    (repo / "backend" / "requirements.txt").write_text("fastapi==1.2.3\n")
    (repo / "frontend" / "package.json").write_text(json.dumps({"dependencies": {"react": "1.2.3"}}))
    (repo / "frontend" / "package-lock.json").write_text("{}\n")
    (repo / "docker-compose.yml").write_text("services: {}\n")
    (repo / "app.py").write_text("print('base')\n")
    base_sha = commit_all(repo, "base")

    (repo / "backend" / "requirements.txt").write_text("fastapi==1.2.4\n")
    patch_sha = commit_all(repo, "chore: bump fastapi patch")
    patch = agent.classify_update(repo, base_sha, patch_sha, dirty=False)
    assert patch["classification"] == "dependency_patch_or_security"
    assert patch["auto_apply_eligible"] is True
    assert patch["requires_approval"] is False
    assert patch["backup_required"] is False

    (repo / "frontend" / "package.json").write_text(json.dumps({"dependencies": {"react": "2.0.0"}}))
    major_sha = commit_all(repo, "chore: bump react major")
    major = agent.classify_update(repo, patch_sha, major_sha, dirty=False)
    assert major["classification"] == "dependency_requires_review"
    assert major["auto_apply_eligible"] is False
    assert major["requires_approval"] is True
    assert major["backup_required"] is False

    (repo / "docker-compose.yml").write_text("services:\n  valkey:\n    image: valkey/valkey:8.1\n")
    runtime_sha = commit_all(repo, "chore: bump runtime image")
    runtime = agent.classify_update(repo, major_sha, runtime_sha, dirty=False)
    assert runtime["classification"] == "runtime_image_or_build_change"
    assert runtime["requires_approval"] is True
    assert runtime["backup_required"] is True

    (repo / "app.py").write_text("print('application change')\n")
    app_sha = commit_all(repo, "feat: application change")
    app_change = agent.classify_update(repo, runtime_sha, app_sha, dirty=False)
    assert app_change["classification"] == "application_or_unknown_change"
    assert app_change["requires_approval"] is True
    assert app_change["backup_required"] is False

    (repo / "backend" / "alembic" / "versions").mkdir(parents=True)
    (repo / "backend" / "alembic" / "versions" / "0001_test.py").write_text("revision = '0001'\n")
    migration_sha = commit_all(repo, "feat: add migration")
    migration_change = agent.classify_update(repo, app_sha, migration_sha, dirty=False)
    assert migration_change["classification"] == "application_or_unknown_change"
    assert migration_change["backup_required"] is True


def test_release_agent_appends_release_history_entries(tmp_path):
    agent = load_release_agent()
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init")
    run_git(repo, "config", "user.email", "test@example.invalid")
    run_git(repo, "config", "user.name", "Medusa Test")
    (repo / "app.py").write_text("print('base')\n")
    base_sha = commit_all(repo, "base")
    (repo / "app.py").write_text("print('release history')\n")
    release_sha = commit_all(repo, "feat: add release history page")
    args = SimpleNamespace(repo=repo, data_dir=tmp_path / "data", history_file=tmp_path / "release-history.json")
    target = agent.release_version(repo, release_sha, "main", "git-local")

    agent.append_release_history(
        args,
        previous_sha=base_sha,
        target_sha=release_sha,
        target=target,
        source="upgrade",
        classification={"changed_files": ["app.py"]},
    )
    agent.append_release_history(
        args,
        previous_sha=base_sha,
        target_sha=release_sha,
        target=target,
        source="upgrade",
        classification={"changed_files": ["app.py"]},
    )

    payload = json.loads(args.history_file.read_text())
    assert payload["schema_version"] == agent.SCHEMA_VERSION
    assert len(payload["entries"]) == 1
    entry = payload["entries"][0]
    assert entry["git_sha"] == release_sha
    assert entry["git_sha_short"] == release_sha[:12]
    assert entry["previous_git_sha"] == base_sha
    assert entry["source"] == "upgrade"
    assert entry["changed_files"] == ["app.py"]
    assert entry["changes"] == [
        {
            "title": "add release history page",
            "description": "Add release history page.",
        }
    ]


def test_release_agent_validates_haproxy_tls_material(tmp_path):
    agent = load_release_agent()

    with pytest.raises(RuntimeError, match="HAProxy TLS material is missing"):
        agent.validate_haproxy_tls_material(tmp_path)

    write_haproxy_tls_placeholders(tmp_path)
    agent.validate_haproxy_tls_material(tmp_path)


def test_release_agent_does_not_run_compose_when_haproxy_tls_is_missing(monkeypatch, tmp_path):
    agent = load_release_agent()
    args = SimpleNamespace(
        repo=tmp_path,
        data_dir=tmp_path / "data",
        status_file=tmp_path / "release-status.json",
        request_file=None,
        remote="origin",
        upstream=None,
        compose_file=["docker-compose.yml"],
        no_fetch=True,
        force=True,
        force_window=True,
        ignore_active_sessions=True,
        idle_grace_seconds=300,
        maintenance_window="03:00-06:00",
        maintenance_timezone="UTC",
        health_timeout_seconds=1,
    )
    compose_calls = []

    monkeypatch.setattr(
        agent,
        "build_status",
        lambda *_args, **_kwargs: {
            "maintenance": {
                "requires_approval": False,
                "message": "Runtime refresh.",
                "backup_required": False,
            }
        },
    )
    monkeypatch.setattr(agent, "update_maintenance_status", lambda *_args, **_kwargs: {})

    def fail_if_readiness_runs(*_args, **_kwargs):
        raise AssertionError("readiness should not run before HAProxy cert preflight")

    def fake_run_command(command, **_kwargs):
        if command[:2] == ["docker", "compose"]:
            compose_calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(agent, "check_maintenance_readiness", fail_if_readiness_runs)
    monkeypatch.setattr(agent, "run_command", fake_run_command)

    assert agent.auto_maintenance(args) == 1
    assert compose_calls == []


def test_release_agent_does_not_run_compose_when_required_backup_gate_fails(monkeypatch, tmp_path):
    agent = load_release_agent()
    write_haproxy_tls_placeholders(tmp_path)
    args = SimpleNamespace(
        repo=tmp_path,
        data_dir=tmp_path / "data",
        status_file=tmp_path / "release-status.json",
        request_file=None,
        remote="origin",
        upstream=None,
        compose_file=["docker-compose.yml"],
        no_fetch=True,
        force=True,
        force_window=True,
        ignore_active_sessions=True,
        idle_grace_seconds=300,
        maintenance_window="03:00-06:00",
        maintenance_timezone="UTC",
        health_timeout_seconds=1,
    )
    compose_calls = []

    monkeypatch.setattr(
        agent,
        "build_status",
        lambda *_args, **_kwargs: {
            "maintenance": {
                "requires_approval": False,
                "message": "Database-sensitive maintenance.",
                "backup_required": True,
            }
        },
    )
    monkeypatch.setattr(agent, "update_maintenance_status", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(agent, "check_maintenance_readiness", lambda *_args, **_kwargs: {"idle": True, "blockers": []})

    def fail_backup(*_args, **_kwargs):
        raise RuntimeError("backup failed")

    def fake_run_command(command, **_kwargs):
        if command[:2] == ["docker", "compose"]:
            compose_calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(agent, "run_pre_maintenance_backup", fail_backup)
    monkeypatch.setattr(agent, "run_command", fake_run_command)

    assert agent.auto_maintenance(args) == 1
    assert compose_calls == []


def test_release_agent_readiness_reports_json_blockers_instead_of_stderr_noise(monkeypatch, tmp_path):
    agent = load_release_agent()
    args = SimpleNamespace(
        repo=tmp_path,
        compose_file=["docker-compose.yml"],
        idle_grace_seconds=300,
    )
    payload = {
        "idle": False,
        "blockers": ["database maintenance is running"],
    }

    def fake_run_command(_command, **_kwargs):
        return SimpleNamespace(
            returncode=1,
            stdout=json.dumps(payload) + "\n",
            stderr=(
                "INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.\n"
                "INFO  [alembic.runtime.migration] Will assume transactional DDL.\n"
            ),
        )

    monkeypatch.setattr(agent, "run_command", fake_run_command)

    with pytest.raises(RuntimeError, match="database maintenance is running") as exc:
        agent.check_maintenance_readiness(args, ignore_active_sessions=True)

    assert "alembic.runtime.migration" not in str(exc.value)


def test_release_agent_keeps_metrics_overlay_optional(monkeypatch, tmp_path):
    agent = load_release_agent()
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    (tmp_path / "docker-compose.server.yml").write_text("services: {}\n")
    (tmp_path / "docker-compose.metrics.yml").write_text("services: {}\n")
    args = SimpleNamespace(repo=tmp_path, compose_file=["docker-compose.yml", "docker-compose.server.yml"])

    monkeypatch.delenv("MEDUSA_METRICS_OVERLAY", raising=False)
    monkeypatch.delenv("MEDUSA_METRICS_ENABLED", raising=False)
    monkeypatch.delenv("MEDUSA_METRICS_INTERNAL_TOKEN", raising=False)
    monkeypatch.delenv("MEDUSA_METRICS_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("MEDUSA_METRICS_BEARER_TOKEN_FILE", raising=False)

    assert agent.compose_base_command(args) == [
        "docker",
        "compose",
        "-f",
        "docker-compose.yml",
        "-f",
        "docker-compose.server.yml",
    ]


def test_release_agent_preserves_enabled_metrics_overlay(monkeypatch, tmp_path):
    agent = load_release_agent()
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    (tmp_path / "docker-compose.server.yml").write_text("services: {}\n")
    (tmp_path / "docker-compose.metrics.yml").write_text("services: {}\n")
    token_file = tmp_path / "data" / "secrets" / "prometheus-token"
    token_file.parent.mkdir(parents=True)
    token_file.write_text("secret\n")
    args = SimpleNamespace(repo=tmp_path, compose_file=["docker-compose.yml", "docker-compose.server.yml"])

    monkeypatch.delenv("MEDUSA_METRICS_OVERLAY", raising=False)
    monkeypatch.delenv("MEDUSA_METRICS_ENABLED", raising=False)
    monkeypatch.delenv("MEDUSA_METRICS_INTERNAL_TOKEN", raising=False)
    monkeypatch.delenv("MEDUSA_METRICS_BEARER_TOKEN", raising=False)
    monkeypatch.setenv("MEDUSA_METRICS_BEARER_TOKEN_FILE", "/app/data/secrets/prometheus-token")

    assert agent.compose_base_command(args) == [
        "docker",
        "compose",
        "-f",
        "docker-compose.yml",
        "-f",
        "docker-compose.server.yml",
        "-f",
        "docker-compose.metrics.yml",
    ]


def test_release_agent_allows_metrics_overlay_opt_out(monkeypatch, tmp_path):
    agent = load_release_agent()
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    (tmp_path / "docker-compose.server.yml").write_text("services: {}\n")
    (tmp_path / "docker-compose.metrics.yml").write_text("services: {}\n")
    (tmp_path / "data" / "secrets").mkdir(parents=True)
    (tmp_path / "data" / "secrets" / "prometheus-token").write_text("secret\n")
    args = SimpleNamespace(repo=tmp_path, compose_file=["docker-compose.yml", "docker-compose.server.yml"])

    monkeypatch.setenv("MEDUSA_METRICS_OVERLAY", "false")

    assert agent.compose_base_command(args) == [
        "docker",
        "compose",
        "-f",
        "docker-compose.yml",
        "-f",
        "docker-compose.server.yml",
    ]


def test_release_agent_reaches_pull_refresh_without_backup_when_not_required(monkeypatch, tmp_path):
    agent = load_release_agent()
    write_haproxy_tls_placeholders(tmp_path)
    args = SimpleNamespace(
        repo=tmp_path,
        data_dir=tmp_path / "data",
        status_file=tmp_path / "release-status.json",
        request_file=None,
        remote="origin",
        upstream=None,
        compose_file=["docker-compose.yml", "docker-compose.server.yml"],
        no_fetch=True,
        force=True,
        force_window=True,
        ignore_active_sessions=True,
        idle_grace_seconds=300,
        maintenance_window="03:00-06:00",
        maintenance_timezone="UTC",
        health_timeout_seconds=1,
    )
    compose_calls = []
    status_payload = {
        "maintenance": {
            "requires_approval": False,
            "message": "Runtime refresh.",
            "auto_apply_eligible": True,
            "backup_required": False,
        }
    }

    monkeypatch.setattr(agent, "build_status", lambda *_args, **_kwargs: dict(status_payload))
    monkeypatch.setattr(agent, "update_maintenance_status", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(agent, "check_maintenance_readiness", lambda *_args, **_kwargs: {"idle": True, "blockers": []})
    monkeypatch.setattr(agent, "maintenance_readiness_payload", lambda *_args, **_kwargs: {"idle": True, "blockers": []})

    def fail_if_backup_runs(*_args, **_kwargs):
        raise AssertionError("backup should not run")

    monkeypatch.setattr(agent, "run_pre_maintenance_backup", fail_if_backup_runs)
    monkeypatch.setattr(agent, "current_branch", lambda _repo: "main")
    monkeypatch.setattr(agent, "upstream_ref", lambda _repo, _remote, _branch, _upstream: "origin/main")
    monkeypatch.setattr(
        agent,
        "git",
        lambda _repo, *command, **_kwargs: "a" * 40 if command == ("rev-parse", "HEAD") or command == ("rev-parse", "origin/main") else "",
    )
    monkeypatch.setattr(
        agent,
        "release_version",
        lambda _repo, _sha, branch, source: {
            "version": "20260627 (aaaaaaaaaaaa)",
            "git_sha": "a" * 40,
            "git_sha_short": "aaaaaaaaaaaa",
            "branch": branch,
            "source": source,
        },
    )
    monkeypatch.setattr(agent, "persist_build_identity", lambda _repo, _target: {"MEDUSA_BUILD_VERSION": "20260627 (aaaaaaaaaaaa)"})
    monkeypatch.setattr(agent, "wait_for_health", lambda *_args, **_kwargs: None)

    def fake_run_command(command, **_kwargs):
        if command[:2] == ["docker", "compose"]:
            compose_calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(agent, "run_command", fake_run_command)

    assert agent.auto_maintenance(args) == 0
    assert compose_calls == [
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.server.yml",
            "pull",
            "--ignore-buildable",
            "--policy",
            "always",
        ],
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.server.yml",
            "build",
            "--pull",
        ],
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.server.yml",
            "up",
            "-d",
            "--no-build",
        ],
    ]


def test_release_agent_rechecks_readiness_after_build_before_replacement(monkeypatch, tmp_path):
    agent = load_release_agent()
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    args = SimpleNamespace(repo=tmp_path, compose_file=["docker-compose.yml"], idle_grace_seconds=300)
    compose_calls = []

    def fake_run_command(command, **_kwargs):
        if command[:2] == ["docker", "compose"]:
            compose_calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(agent, "run_command", fake_run_command)
    monkeypatch.setattr(agent, "maintenance_readiness_payload", lambda *_args, **_kwargs: {"idle": False, "blockers": ["1 active import job"]})

    with pytest.raises(RuntimeError, match="1 active import job"):
        agent.run_compose_refresh(args, readiness_context="Upgrade became blocked before replacing Medusa services")

    assert compose_calls == [["docker", "compose", "-f", "docker-compose.yml", "build"]]


def test_release_agent_compose_passthrough_blocks_rebuild_with_active_work(monkeypatch, tmp_path, capsys):
    agent = load_release_agent()
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    args = SimpleNamespace(
        repo=tmp_path,
        compose_file=["docker-compose.yml"],
        compose_args=["--", "up", "-d", "--build"],
        idle_grace_seconds=300,
        skip_readiness=False,
    )

    monkeypatch.setattr(agent, "maintenance_readiness_payload", lambda *_args, **_kwargs: {"idle": False, "blockers": ["2 active import jobs"]})

    def fail_if_compose_runs(*_args, **_kwargs):
        raise AssertionError("docker compose should not run")

    monkeypatch.setattr(agent.subprocess, "run", fail_if_compose_runs)

    assert agent.compose_passthrough(args) == 1
    assert "2 active import jobs" in capsys.readouterr().err
