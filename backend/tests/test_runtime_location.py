from app.services.runtime_location import normalize_host, runtime_location_payload


def test_runtime_location_marks_loopback_as_local():
    payload = runtime_location_payload("localhost", "192.168.1.20")

    assert payload["network_context"] == "local"
    assert payload["ipv4"] is None
    assert payload["title"] == "medusa (local)"


def test_runtime_location_marks_private_ipv4_as_lan():
    payload = runtime_location_payload("192.168.1.20")

    assert payload["network_context"] == "lan"
    assert payload["ipv4"] == "192.168.1.20"
    assert payload["title"] == "medusa (local: 192.168.1.20)"


def test_runtime_location_marks_public_ipv4_as_remote():
    payload = runtime_location_payload("8.8.8.8")

    assert payload["network_context"] == "remote"
    assert payload["ipv4"] == "8.8.8.8"
    assert payload["title"] == "medusa (remote: 8.8.8.8)"


def test_runtime_location_normalizes_url_hosts_and_uses_server_fallback():
    assert normalize_host("http://192.168.1.20:3737/path") == "192.168.1.20"

    payload = runtime_location_payload("", "10.0.0.5")

    assert payload["network_context"] == "lan"
    assert payload["title"] == "medusa (local: 10.0.0.5)"
