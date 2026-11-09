"""Static checks of the mesh authorization policy (no cluster needed).

The expected matrix below is the reviewed list of allowed operations from
docs/04-service-contracts-and-policies.md. Any change to deploy/istio/security.yaml
that widens access must also change this table, which makes the change visible
in review.
"""

from pathlib import Path

import yaml

POLICY_FILE = Path(__file__).resolve().parents[2] / "deploy" / "istio" / "security.yaml"
SA = "cluster.local/ns/default/sa/"

# Policies that intentionally accept any caller.
OPEN_POLICIES = {"allow-frontend-ingress", "allow-health-probes"}
# TCP services: the mesh can only check caller identity and port.
TCP_TARGETS = {"postgres"}

EXPECTED_OPERATIONS = {
    ("product", "frontend"): {("GET", "/products")},
    ("product", "cart"): {("GET", "/products/{*}")},
    ("cart", "frontend"): {
        ("GET", "/carts/{*}"),
        ("PUT", "/carts/{*}/items"),
        ("DELETE", "/carts/{*}/items/{*}"),
        ("POST", "/carts/{*}/checkout"),
    },
    ("order", "cart"): {
        ("POST", "/orders"),
        ("POST", "/orders/{*}/reserve"),
        ("POST", "/orders/{*}/confirm"),
    },
    ("inventory", "order"): {("POST", "/reservations"), ("DELETE", "/reservations/{*}")},
    ("payment", "order"): {("POST", "/authorizations")},
    ("notification", "order"): {("POST", "/events/order")},
    ("keycloak", "frontend"): {
        ("POST", "/realms/ecommerce/protocol/openid-connect/token"),
        ("GET", "/realms/ecommerce/protocol/openid-connect/certs"),
    },
    ("opa", "frontend"): {("POST", "/v1/data/ecommerce/authz/decision")},
}

EXPECTED_DB_CLIENTS = {
    "product",
    "cart",
    "order",
    "inventory",
    "payment",
    "notification",
    "db-bootstrap",
}


def _documents() -> list[dict]:
    return [doc for doc in yaml.safe_load_all(POLICY_FILE.read_text()) if doc]


def _allow_policies() -> list[dict]:
    return [
        doc
        for doc in _documents()
        if doc["kind"] == "AuthorizationPolicy" and doc["spec"].get("action") == "ALLOW"
    ]


def _target(policy: dict) -> str:
    return policy["spec"]["selector"]["matchLabels"]["app"]


def test_mtls_is_strict_and_default_deny_exists() -> None:
    docs = {(doc["kind"], doc["metadata"]["name"]): doc for doc in _documents()}
    assert docs[("PeerAuthentication", "default")]["spec"]["mtls"]["mode"] == "STRICT"
    assert docs[("AuthorizationPolicy", "default-deny-ingress")]["spec"] == {}


def test_every_non_public_allow_rule_names_its_callers() -> None:
    for policy in _allow_policies():
        if policy["metadata"]["name"] in OPEN_POLICIES:
            continue
        for rule in policy["spec"]["rules"]:
            principals = [p for src in rule["from"] for p in src["source"]["principals"]]
            assert principals, policy["metadata"]["name"]
            assert all(p.startswith(SA) and not p.endswith("*") for p in principals)


def test_every_http_allow_rule_names_methods_and_paths() -> None:
    for policy in _allow_policies():
        name = policy["metadata"]["name"]
        if name == "allow-frontend-ingress" or _is_tcp(policy):
            continue
        for rule in policy["spec"]["rules"]:
            for to in rule["to"]:
                operation = to["operation"]
                assert operation.get("methods"), name
                assert operation.get("paths"), name
                assert all(path != "*" and path != "/*" for path in operation["paths"]), name


def _is_tcp(policy: dict) -> bool:
    selector = policy["spec"].get("selector")
    return bool(selector) and _target(policy) in TCP_TARGETS


def test_allowed_operations_match_the_reviewed_matrix() -> None:
    observed: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for policy in _allow_policies():
        if policy["metadata"]["name"] in OPEN_POLICIES or _is_tcp(policy):
            continue
        target = _target(policy)
        for rule in policy["spec"]["rules"]:
            callers = [
                p.removeprefix(SA) for src in rule["from"] for p in src["source"]["principals"]
            ]
            for caller in callers:
                for to in rule["to"]:
                    for method in to["operation"]["methods"]:
                        for path in to["operation"]["paths"]:
                            observed.setdefault((target, caller), set()).add((method, path))
    assert observed == EXPECTED_OPERATIONS


def test_business_edges_match_assignment_matrix() -> None:
    """Seven of the 42 directed workload pairs are allowed (Assignment 2, section 3)."""
    workloads = {"frontend", "product", "cart", "order", "inventory", "payment", "notification"}
    edges = {pair for pair in EXPECTED_OPERATIONS if pair[0] in workloads}
    assert len(edges) == 7


def test_database_clients_are_the_owning_services_only() -> None:
    (policy,) = [p for p in _allow_policies() if _is_tcp(p)]
    principals = {
        p.removeprefix(SA)
        for rule in policy["spec"]["rules"]
        for src in rule["from"]
        for p in src["source"]["principals"]
    }
    assert principals == EXPECTED_DB_CLIENTS
    assert all(
        to["operation"]["ports"] == ["5432"]
        for rule in policy["spec"]["rules"]
        for to in rule["to"]
    )
