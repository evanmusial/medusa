import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace


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

    (repo / "frontend" / "package.json").write_text(json.dumps({"dependencies": {"react": "2.0.0"}}))
    major_sha = commit_all(repo, "chore: bump react major")
    major = agent.classify_update(repo, patch_sha, major_sha, dirty=False)
    assert major["classification"] == "dependency_requires_review"
    assert major["auto_apply_eligible"] is False
    assert major["requires_approval"] is True

    (repo / "docker-compose.yml").write_text("services:\n  valkey:\n    image: valkey/valkey:8.1\n")
    runtime_sha = commit_all(repo, "chore: bump runtime image")
    runtime = agent.classify_update(repo, major_sha, runtime_sha, dirty=False)
    assert runtime["classification"] == "runtime_image_or_build_change"
    assert runtime["requires_approval"] is True

    (repo / "app.py").write_text("print('application change')\n")
    app_sha = commit_all(repo, "feat: application change")
    app_change = agent.classify_update(repo, runtime_sha, app_sha, dirty=False)
    assert app_change["classification"] == "application_or_unknown_change"
    assert app_change["requires_approval"] is True


def test_release_agent_does_not_run_compose_when_backup_gate_fails(monkeypatch, tmp_path):
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
                "message": "Dependency-only patch/security update.",
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


def test_release_agent_reaches_pull_refresh_after_successful_backup(monkeypatch, tmp_path):
    agent = load_release_agent()
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
        }
    }

    monkeypatch.setattr(agent, "build_status", lambda *_args, **_kwargs: dict(status_payload))
    monkeypatch.setattr(agent, "update_maintenance_status", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(agent, "check_maintenance_readiness", lambda *_args, **_kwargs: {"idle": True, "blockers": []})
    monkeypatch.setattr(agent, "run_pre_maintenance_backup", lambda *_args, **_kwargs: {"id": "backup-1", "verified": True})
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
            "up",
            "-d",
            "--build",
            "--pull",
            "always",
        ]
    ]
