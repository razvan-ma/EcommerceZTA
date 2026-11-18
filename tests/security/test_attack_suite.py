"""Offline checks for the attack suite's own logic (no cluster needed)."""

import pytest

from tests.security.compare import fisher_exact
from tests.security.run_attacks import classify, forged_tokens, jwt_parts, redact


@pytest.mark.parametrize(
    ("run", "kind", "expected"),
    [
        ({"status": 201, "body": "{}"}, "http", ("allowed", "-")),
        ({"status": 403, "body": "RBAC: access denied"}, "http", ("blocked", "mesh")),
        ({"status": 403, "body": '{"detail":"no policy rule"}'}, "http", ("blocked", "application")),
        ({"status": 401, "body": "{}"}, "http", ("blocked", "application")),
        ({"status": None, "error": "ConnectionResetError: reset"}, "http", ("blocked", "transport")),
        ({"status": None, "error": "InsufficientPrivilege: denied"}, "sql", ("blocked", "database")),
        ({"status": "ok", "body": "1 rows"}, "sql", ("allowed", "-")),
        ({"status": 404, "body": "{}"}, "http", ("inconclusive", "status 404")),
    ],
)
def test_classify(run, kind, expected) -> None:
    success = ["ok"] if kind == "sql" else [200, 201]
    assert classify(run, success, [401, 403], kind) == expected


def test_policy_outage_counts_as_fail_closed_only_when_declared() -> None:
    run = {"status": 503, "body": '{"detail":"authorization service unavailable"}'}
    assert classify(run, [200], [401, 403, 503]) == ("blocked", "fail-closed")
    assert classify(run, [200], [401, 403])[0] == "inconclusive"


def test_fisher_exact_matches_known_values() -> None:
    assert fisher_exact(3, 1, 1, 3) == pytest.approx(0.4857, abs=1e-4)  # lady tasting tea
    assert fisher_exact(10, 0, 0, 10) == pytest.approx(2 / 184756)
    assert fisher_exact(5, 5, 5, 5) == pytest.approx(1.0)


def test_forged_tokens_keep_claims_but_cannot_carry_a_valid_signature() -> None:
    real = "eyJhbGciOiJSUzI1NiIsImtpZCI6ImsxIn0.eyJwcmVmZXJyZWRfdXNlcm5hbWUiOiJjdXN0b21lci0xIn0.c2ln"
    forged = forged_tokens(real)
    header, claims, signature = jwt_parts(forged["tampered"])
    assert claims["preferred_username"] == "customer-2" and signature == "c2ln"
    assert jwt_parts(forged["none"])[0]["alg"] == "none"
    assert jwt_parts(forged["hs256"])[0] == {"alg": "HS256", "typ": "JWT", "kid": "k1"}


def test_tokens_are_redacted_from_stored_bodies() -> None:
    assert redact('{"access_token":"eyJa.eyJb.c2ln"}') == '{"access_token":"<jwt>"}'
