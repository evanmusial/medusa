import json


def reset_settings_cache():
    from app.config import get_settings

    get_settings.cache_clear()


def write_status(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def test_release_status_detects_upgrade_and_writes_request(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    reset_settings_cache()

    from app.services.release_status import release_status, request_release_upgrade

    status_path = tmp_path / "data" / "deploy" / "release-status.json"
    request_path = tmp_path / "data" / "deploy" / "release-request.json"
    write_status(
        status_path,
        {
            "checked_at": "2026-06-25T12:00:00+00:00",
            "phase": "update_available",
            "message": "A newer Medusa release is available.",
            "update_available": True,
            "apply_available": True,
            "dirty": False,
            "running": {
                "version": "20260624 (aaaaaaaaaaaa)",
                "git_sha": "a" * 40,
                "git_sha_short": "aaaaaaaaaaaa",
                "branch": "main",
                "source": "git-local",
            },
            "available": {
                "version": "20260625 (bbbbbbbbbbbb)",
                "git_sha": "b" * 40,
                "git_sha_short": "bbbbbbbbbbbb",
                "branch": "main",
                "source": "git-upstream",
            },
        },
    )

    status = release_status(client_version="20260624 (aaaaaaaaaaaa)")
    assert status.update_available is True
    assert status.apply_available is True
    assert status.browser_reload_recommended is False
    assert status.maintenance_backup_required is False
    assert status.maintenance_backup_status == "not_required"

    requested = request_release_upgrade(client_version="20260624 (aaaaaaaaaaaa)", requested_by="admin@medusa.local")
    assert requested.phase == "requested"
    assert requested.request_id
    request_payload = json.loads(request_path.read_text())
    assert request_payload["requested_by"] == "admin@medusa.local"
    assert request_payload["target"]["version"] == "20260625 (bbbbbbbbbbbb)"

    reset_settings_cache()


def test_release_status_recommends_browser_reload_for_completed_release_request(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    reset_settings_cache()

    from app.services.release_status import release_status

    write_status(
        tmp_path / "data" / "deploy" / "release-status.json",
        {
            "checked_at": "2026-06-25T12:00:00+00:00",
            "phase": "complete",
            "message": "Medusa upgraded to 20260625 (bbbbbbbbbbbb).",
            "request_id": "release-request-1",
            "requested_at": "2026-06-25T11:59:00+00:00",
            "update_available": False,
            "apply_available": False,
            "dirty": False,
            "running": {
                "version": "20260625 (bbbbbbbbbbbb)",
                "git_sha": "b" * 40,
                "git_sha_short": "bbbbbbbbbbbb",
                "branch": "main",
                "source": "git-local",
            },
            "available": {
                "version": "20260625 (bbbbbbbbbbbb)",
                "git_sha": "b" * 40,
                "git_sha_short": "bbbbbbbbbbbb",
                "branch": "main",
                "source": "git-upstream",
            },
        },
    )

    status = release_status(client_version="20260624 (aaaaaaaaaaaa)")
    assert status.update_available is False
    assert status.browser_reload_recommended is True
    assert status.phase == "complete"
    assert status.request_id == "release-request-1"

    reset_settings_cache()


def test_release_status_suppresses_browser_reload_for_settled_maintenance_refresh(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    reset_settings_cache()

    from app.services.release_status import release_status

    write_status(
        tmp_path / "data" / "deploy" / "release-status.json",
        {
            "checked_at": "2026-06-25T12:00:00+00:00",
            "phase": "complete",
            "message": "Medusa maintenance completed for 20260625 (bbbbbbbbbbbb).",
            "update_available": False,
            "apply_available": False,
            "dirty": False,
            "running": {
                "version": "20260625 (bbbbbbbbbbbb)",
                "git_sha": "b" * 40,
                "git_sha_short": "bbbbbbbbbbbb",
                "branch": "main",
                "source": "git-local",
            },
            "available": {
                "version": "20260625 (bbbbbbbbbbbb)",
                "git_sha": "b" * 40,
                "git_sha_short": "bbbbbbbbbbbb",
                "branch": "main",
                "source": "git-local",
            },
            "maintenance": {
                "phase": "complete",
                "message": "Maintenance completed; database backup was not required for this refresh.",
                "update_classification": "runtime_refresh",
                "backup_required": False,
                "backup_status": "not_required",
            },
        },
    )

    status = release_status(client_version="20260624 (aaaaaaaaaaaa)")
    assert status.update_available is False
    assert status.browser_reload_recommended is False
    assert status.phase == "complete"

    reset_settings_cache()


def test_release_status_prefers_runtime_identity_over_stale_status_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEDUSA_BUILD_VERSION", "20260627 (bbbbbbbbbbbb)")
    monkeypatch.setenv("MEDUSA_BUILD_DATE", "20260627")
    monkeypatch.setenv("MEDUSA_BUILD_HASH", "bbbbbbbbbbbb")
    monkeypatch.setenv("MEDUSA_GIT_SHA", "b" * 40)
    reset_settings_cache()

    from app.services.release_status import release_status

    write_status(
        tmp_path / "data" / "deploy" / "release-status.json",
        {
            "checked_at": "2026-06-26T12:00:00+00:00",
            "phase": "current",
            "message": "The server checkout has local changes; automatic upgrade is blocked.",
            "update_available": False,
            "apply_available": False,
            "dirty": True,
            "running": {
                "version": "20260626 (aaaaaaaaaaaa)",
                "git_sha": "a" * 40,
                "git_sha_short": "aaaaaaaaaaaa",
                "branch": "main",
                "source": "git-local",
            },
            "available": {
                "version": "20260626 (aaaaaaaaaaaa)",
                "git_sha": "a" * 40,
                "git_sha_short": "aaaaaaaaaaaa",
                "branch": "main",
                "source": "git-upstream",
            },
        },
    )

    status = release_status(client_version="20260627 (bbbbbbbbbbbb)")
    assert status.running.version == "20260627 (bbbbbbbbbbbb)"
    assert status.running.git_sha == "b" * 40
    assert status.available and status.available.version == "20260627 (bbbbbbbbbbbb)"
    assert status.update_available is False
    assert status.apply_available is False
    assert status.browser_reload_recommended is False
    assert status.phase == "current"
    assert status.dirty is False

    reset_settings_cache()


def test_release_status_writes_check_and_maintenance_requests(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    reset_settings_cache()

    from app.services.release_status import request_maintenance_run, request_release_check

    checked = request_release_check(client_version="20260627 (aaaaaaaaaaaa)", requested_by="admin@medusa.local")
    check_path = tmp_path / "data" / "deploy" / "release-check-request.json"
    check_payload = json.loads(check_path.read_text())

    assert checked.maintenance_phase == "idle"
    assert check_payload["requested_by"] == "admin@medusa.local"
    assert check_payload["client_version"] == "20260627 (aaaaaaaaaaaa)"

    maintenance = request_maintenance_run(client_version="20260627 (aaaaaaaaaaaa)", requested_by="admin@medusa.local")
    maintenance_path = tmp_path / "data" / "deploy" / "maintenance-request.json"
    maintenance_payload = json.loads(maintenance_path.read_text())

    assert maintenance.maintenance_phase == "requested"
    assert maintenance_payload["requested_by"] == "admin@medusa.local"
    assert maintenance_payload["ignore_active_sessions"] is True
    assert maintenance_payload["force_window"] is True

    reset_settings_cache()
