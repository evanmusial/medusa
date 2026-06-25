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

    requested = request_release_upgrade(client_version="20260624 (aaaaaaaaaaaa)", requested_by="admin@medusa.local")
    assert requested.phase == "requested"
    assert requested.request_id
    request_payload = json.loads(request_path.read_text())
    assert request_payload["requested_by"] == "admin@medusa.local"
    assert request_payload["target"]["version"] == "20260625 (bbbbbbbbbbbb)"

    reset_settings_cache()


def test_release_status_recommends_browser_reload_when_server_is_newer(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDUSA_DATA_DIR", str(tmp_path / "data"))
    reset_settings_cache()

    from app.services.release_status import release_status

    write_status(
        tmp_path / "data" / "deploy" / "release-status.json",
        {
            "checked_at": "2026-06-25T12:00:00+00:00",
            "phase": "current",
            "message": "Medusa is current.",
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
    assert status.phase == "reload_ready"

    reset_settings_cache()
