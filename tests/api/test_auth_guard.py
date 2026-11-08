"""Offline regression tests for the Modal CPU gateway security perimeter."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from multilingual_translation_ai_inference.api import create_api
from multilingual_translation_ai_inference.auth_guard import (
    AuthenticationFailureGuard,
    client_identity,
)
from multilingual_translation_ai_inference.settings import Settings

TOKEN = "offline-translation-api-token-for-tests"
CORRECT = {"Authorization": f"Bearer {TOKEN}"}
WRONG = {"Authorization": "Bearer invalid-guess"}


def app_for_test(**overrides):
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        api_bearer_token=TOKEN,
        **{"dispatcher_mode": "record-only", **overrides},
    )
    # The catalog and invalid-auth checks never access the injected repository.
    return create_api(settings, repository=object(), dispatcher=object())



@pytest.mark.parametrize("size", [16, 4089, 4090, 4096])
def test_full_bearer_token_length_is_valid_without_counting_http_scheme(size):
    secret = "A" * size
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        api_bearer_token=secret,
        dispatcher_mode="record-only",
    )
    with TestClient(create_api(settings, repository=object(), dispatcher=object())) as client:
        response = client.get("/v1/models", headers={"Authorization": f"Bearer {secret}"})
        assert response.status_code == 200
        assert len(response.json()["models"]) == 4
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"

        wrong = client.get("/v1/models", headers={"Authorization": f"Bearer {'B' + secret[1:]}"})
        assert wrong.status_code == 401
        assert wrong.headers["Cache-Control"] == "no-store"
        assert wrong.headers["X-Content-Type-Options"] == "nosniff"
        assert secret not in wrong.text


@pytest.mark.parametrize("size", [15, 4097])
def test_out_of_bounds_authorization_credential_returns_sanitized_401(size):
    with TestClient(app_for_test()) as client:
        response = client.get("/v1/models", headers={"Authorization": f"Bearer {'A' * size}"})
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert "A" * size not in response.text


@pytest.mark.parametrize("scheme", ["Bearer", "bearer", "BEARER", "BeArEr"])
def test_bearer_http_scheme_is_case_insensitive_but_secret_is_not(scheme):
    with TestClient(app_for_test()) as client:
        response = client.get("/v1/models", headers={"Authorization": f"{scheme} {TOKEN}"})
        assert response.status_code == 200
        wrong = client.get("/v1/models", headers={"Authorization": f"{scheme} {TOKEN.upper()}"})
        assert wrong.status_code == 401
        assert TOKEN not in wrong.text


@pytest.mark.parametrize("bad_token", [
    "", "short", "A" * 15, "A" * 4097,
    " " + "A" * 16, "A" * 16 + " ", "A" * 16 + "\n",
    "A" * 8 + " " + "A" * 8, "A" * 8 + "\t" + "A" * 8,
    "A" * 8 + "\n" + "A" * 8, "A" * 8 + "\r" + "A" * 8,
    "A" * 8 + "\0" + "A" * 8, "A" * 8 + "\x7f" + "A" * 8,
    "é" * 16, None, 123,
])
def test_direct_settings_reject_invalid_tokens_without_echoing(bad_token):
    with pytest.raises(ValueError, match="TRANSLATION_API_BEARER_TOKEN") as exc:
        Settings(database_url="sqlite+pysqlite:///:memory:", api_bearer_token=bad_token)
    if isinstance(bad_token, str) and bad_token:
        assert bad_token not in str(exc.value)


@pytest.mark.parametrize("size", [16, 4096])
def test_environment_and_direct_settings_share_valid_token_boundaries(monkeypatch, size):
    secret = "A" * size
    monkeypatch.setenv("TRANSLATION_INFERENCE_DATABASE_URL", "sqlite:///test.db")
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", secret)
    assert Settings.from_environment().api_bearer_token == secret
    assert Settings(database_url="sqlite:///test.db", api_bearer_token=secret).api_bearer_token == secret



@pytest.mark.parametrize("secret", ["A" * 15 + "!", "A" * 4095 + "~"])
def test_printable_ascii_punctuation_is_valid_for_settings_and_gateway(monkeypatch, secret):
    monkeypatch.setenv("TRANSLATION_INFERENCE_DATABASE_URL", "sqlite:///test.db")
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", secret)
    assert Settings.from_environment().api_bearer_token == secret
    settings = Settings(database_url="sqlite+pysqlite:///:memory:", api_bearer_token=secret)
    with TestClient(create_api(settings, repository=object(), dispatcher=object())) as client:
        response = client.get("/v1/models", headers={"Authorization": "Bearer " + secret})
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize("credential", [
    "A" * 8 + " " + "A" * 8,
    "A" * 8 + "\t" + "A" * 8,
    "A" * 8 + "\n" + "A" * 8,
    "A" * 8 + "\0" + "A" * 8,
])
def test_gateway_rejects_nonprintable_or_spaced_http_credentials(credential):
    with TestClient(app_for_test()) as client:
        response = client.get("/v1/models", headers={"Authorization": "Bearer " + credential})
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert credential not in response.text

def test_three_invalid_attempts_lock_out_guesses_across_routes():
    with TestClient(app_for_test(), client=("203.0.113.10", 51001)) as client:
        assert client.get("/v1/models", headers=WRONG).status_code == 401
        second = client.get("/v1/models")
        assert second.status_code == 401
        assert second.headers["WWW-Authenticate"] == "Bearer"
        assert second.headers["Cache-Control"] == "no-store"
        third = client.post("/v1/jobs/translations", content=b"not json", headers=WRONG)
        assert third.status_code == 429
        assert third.json()["detail"] == "Too many failed authentication attempts"
        assert third.headers["Retry-After"] == "900"
        assert client.get("/v1/models", headers=WRONG).status_code == 429


def test_correct_token_bypasses_lockout_and_clears_counter_on_shared_peer():
    with TestClient(app_for_test(), client=("203.0.113.11", 10011)) as client:
        for _ in range(3):
            client.get("/v1/models", headers=WRONG)
        good = client.get("/v1/models", headers=CORRECT)
        assert good.status_code == 200
        assert good.headers["Cache-Control"] == "no-store"
        assert good.headers["X-Content-Type-Options"] == "nosniff"
        assert client.get("/v1/models", headers=WRONG).status_code == 401


def test_other_peer_is_independent_and_forwarded_header_cannot_escape_lockout():
    app = app_for_test()
    with TestClient(app, client=("198.51.100.20", 1111)) as alice:
        with TestClient(app, client=("203.0.113.20", 2222)) as bob:
            for i in range(3):
                r = alice.get("/v1/models", headers={
                    **WRONG, "X-Forwarded-For": f"192.0.2.{i + 10}",
                })
            assert r.status_code == 429
            assert alice.get("/v1/models", headers={
                **WRONG, "Forwarded": "for=203.0.113.100",
            }).status_code == 429
            assert bob.get("/v1/models", headers=WRONG).status_code == 401
            assert bob.get("/v1/models", headers=CORRECT).status_code == 200


def test_wrong_credentials_are_rejected_before_body_parsing():
    with TestClient(app_for_test()) as client:
        wrong = client.post(
            "/v1/jobs/translations", headers={**WRONG, "Content-Length": "90000000"},
            content=b"invalid-json",
        )
        assert wrong.status_code == 401
        assert client.get("/v1/models", headers=CORRECT).status_code == 200


def test_authenticated_request_body_is_bounded_even_without_content_length():
    with TestClient(app_for_test(max_api_body_bytes=64)) as client:
        large = client.post("/v1/jobs/translations", headers=CORRECT, content=b"x" * 65)
        assert large.status_code == 413
        assert large.headers["Cache-Control"] == "no-store"
        assert large.headers["X-Content-Type-Options"] == "nosniff"

        def chunks():
            yield b"x" * 35
            yield b"y" * 35

        chunked = client.post(
            "/v1/jobs/translations", headers=CORRECT, content=chunks(),
        )
        assert chunked.status_code == 413
        assert chunked.headers["Cache-Control"] == "no-store"
        assert chunked.headers["X-Content-Type-Options"] == "nosniff"


def test_invalid_content_length_has_all_protected_error_headers():
    with TestClient(app_for_test()) as client:
        response = client.post(
            "/v1/jobs/translations", headers={**CORRECT, "Content-Length": "not-a-number"},
            content=b"{}",
        )
        assert response.status_code == 400
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_protected_bad_body_and_unknown_routes_do_not_publish_schema():
    with TestClient(app_for_test()) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/health").status_code == 200
        malformed = client.post(
            "/v1/jobs/translations", headers=CORRECT, content=b"not json",
        )
        assert malformed.status_code == 422


def test_catalog_distinguishes_dispatch_from_live_gpu_readiness():
    with TestClient(app_for_test()) as client:
        catalog = client.get("/v1/models", headers=CORRECT).json()["models"]
        assert len(catalog) == 4
        assert all(m["enabled"] is False for m in catalog)
        assert all(m["dispatch_enabled"] is False for m in catalog)
        assert all(m["runtime_status"] == "not_checked" for m in catalog)
        assert all(m["runtime_verified"] is True for m in catalog)
    with TestClient(app_for_test(dispatcher_mode="modal-gpu")) as client:
        catalog = client.get("/v1/models", headers=CORRECT).json()["models"]
        assert len(catalog) == 4
        assert all(m["dispatch_enabled"] and m["enabled"] for m in catalog)
        assert all(m["runtime_status"] == "not_checked" for m in catalog)


def test_sliding_window_expiry_and_lockout_expiry():
    clock = [100.0]
    guard = AuthenticationFailureGuard(
        max_failures=3, window_seconds=60, lockout_seconds=120, clock=lambda: clock[0],
    )
    peer = "192.0.2.1"
    assert guard.record_failure(peer) is None
    assert guard.record_failure(peer) is None
    clock[0] += 61
    assert guard.record_failure(peer) is None
    assert guard.record_failure(peer) is None
    assert guard.record_failure(peer) == 120
    clock[0] += 10
    assert guard.record_failure(peer) == 110
    clock[0] += 110
    assert guard.record_failure(peer) is None


def test_thread_safety_and_bounded_client_memory():
    guard = AuthenticationFailureGuard(max_clients=2)
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(guard.record_failure, ["192.0.2.2"] * 25))
    assert results.count(None) == 2
    assert sum(x is not None for x in results) == 23
    guard.record_failure("192.0.2.3")
    guard.record_failure("192.0.2.4")
    assert len(guard._clients) == 2


def test_invalid_settings_are_rejected_and_no_limits_are_disableable(monkeypatch):
    fields = {
        "TRANSLATION_AUTH_FAILURE_LIMIT": "auth_failure_limit",
        "TRANSLATION_AUTH_FAILURE_WINDOW_SECONDS": "auth_failure_window_seconds",
        "TRANSLATION_AUTH_LOCKOUT_SECONDS": "auth_lockout_seconds",
        "TRANSLATION_AUTH_MAX_TRACKED_CLIENTS": "auth_max_tracked_clients",
        "TRANSLATION_MAX_API_BODY_BYTES": "max_api_body_bytes",
    }
    for env, field in fields.items():
        with pytest.raises(ValueError, match=env):
            app_for_test(**{field: 0})
        monkeypatch.setenv("TRANSLATION_INFERENCE_DATABASE_URL", "sqlite:///test.db")
        monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", TOKEN)
        monkeypatch.setenv(env, "0")
        with pytest.raises(ValueError, match=env):
            Settings.from_environment()
        monkeypatch.delenv(env)


@pytest.mark.parametrize("invalid_token", [
    "short", " nontrimmed-secret-test ", "unicode-secret-óóóóóóóóó",
    "A" * 8 + " " + "A" * 8, "A" * 8 + "\t" + "A" * 8,
    "A" * 8 + "\n" + "A" * 8, "A" * 8 + "\x7f" + "A" * 8,
])
def test_deployment_rejects_weak_or_non_ascii_tokens(monkeypatch, invalid_token):
    monkeypatch.setenv("TRANSLATION_INFERENCE_DATABASE_URL", "sqlite:///test.db")
    monkeypatch.setenv("TRANSLATION_API_BEARER_TOKEN", invalid_token)
    with pytest.raises(RuntimeError, match="TRANSLATION_API_BEARER_TOKEN"):
        Settings.from_environment()


def test_client_identity_ignores_untrusted_headers():
    from starlette.requests import Request

    scope = {
        "type": "http", "method": "GET", "path": "/v1/models",
        "query_string": b"", "server": ("server", 80),
        "client": ("198.51.100.77", 1000),
        "headers": [(b"x-forwarded-for", b"203.0.113.20")],
    }
    assert client_identity(Request(scope)) == "198.51.100.77"
    scope["client"] = ("not-an-ip", 1000)
    assert client_identity(Request(scope)) == "unidentified-peer"
