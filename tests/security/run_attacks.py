"""Security attack suite for the baseline vs Zero-Trust comparison.

Runs the evaluation scenarios of docs/02-threat-model.md (section 7) against
one deployed variant and records, for every attempt, what happened and which
layer stopped it. Run it once per variant, then compare with compare.py:

    python3 tests/security/run_attacks.py --namespace default --variant zero-trust
    python3 tests/security/run_attacks.py --namespace ecommerce-baseline --variant baseline
    python3 tests/security/compare.py

Attacks come from three places, matching the threat model's attacker:
  external   a client with a valid low-privilege customer account, through a
             port-forward to the frontend (the public entry point);
  workload   code running inside a compromised service pod (kubectl exec);
  attacker   extra pods with no mesh identity, or an identity nobody trusts.

Only the Python standard library is used, so the same probe code runs locally
and inside the service images. No secret, token or password is printed or
written to the results; response bodies are redacted and truncated.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "deploy" / "helm" / "ecommerce-platform"
RESULTS = ROOT / "results" / "security"
ATTACKER_MANIFEST = Path(__file__).with_name("attacker.yaml")
USERNAME = "customer-1"
VICTIM = "customer-2"

BLOCKED, ALLOWED, INCONCLUSIVE, NOT_APPLICABLE = "blocked", "allowed", "inconclusive", "n/a"

# --------------------------------------------------------------------------
# Probe code. Runs unchanged locally (exec) and in pods (python -c), reading
# {"probes": [...]} on stdin and printing one result list per probe.
# --------------------------------------------------------------------------
PROBE_SRC = r'''
import json, os, sys, time, urllib.request, urllib.error

def http(p, url=None, method=None):
    url, method = url or p["url"], method or p.get("method", "GET")
    data, ctype = None, "application/json"
    if "json" in p:
        data = json.dumps(p["json"]).encode()
    elif "data" in p:
        data, ctype = p["data"].encode(), "text/plain"
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", ctype)
    for key, value in (p.get("headers") or {}).items():
        req.add_header(key, value)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=p.get("timeout", 8)) as r:
            status, body, error = r.status, r.read().decode("utf-8", "replace"), None
    except urllib.error.HTTPError as e:
        status, body, error = e.code, e.read().decode("utf-8", "replace"), None
    except Exception as e:
        status, body, error = None, "", "%s: %s" % (type(e).__name__, e)
    return {"status": status, "body": body[:2000], "error": error,
            "ms": round((time.perf_counter() - start) * 1000, 1)}

def sql(p):
    import psycopg
    start, errors = time.perf_counter(), []
    for statement in p["sql"]:
        try:
            conn = psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5)
        except Exception as e:
            errors.append("connect: %s" % type(e).__name__)
            break
        try:
            with conn.cursor() as cur:
                cur.execute(statement)
                rows = len(cur.fetchall()) if cur.description else cur.rowcount
            return {"status": "ok", "body": "%s -> %d rows (rolled back)" % (statement, rows),
                    "error": None, "ms": round((time.perf_counter() - start) * 1000, 1)}
        except Exception as e:
            errors.append("%s: %s" % (type(e).__name__, str(e).splitlines()[0]))
        finally:
            conn.rollback()  # writes are only attempted, never kept
            conn.close()
    return {"status": None, "body": "", "error": "; ".join(errors),
            "ms": round((time.perf_counter() - start) * 1000, 1)}

def run_probes(probes):
    out = []
    for p in probes:
        runs = []
        for _ in range(p.get("repeat", 1)):
            r = sql(p) if p.get("kind") == "sql" else http(p)
            cleanup = p.get("cleanup")
            if cleanup and r["status"] in p["success"]:
                try:
                    fields = json.loads(r["body"]) if r["body"].startswith("{") else {}
                except ValueError:
                    fields = {}
                c = http(p, url=cleanup["url"].format(**fields), method=cleanup["method"])
                r["cleanup_status"] = c["status"]
            runs.append(r)
        out.append(runs)
    return out

if __name__ == "__main__":
    print(json.dumps(run_probes(json.loads(sys.stdin.read())["probes"])))
'''
_probe_ns: dict = {}
exec(PROBE_SRC, _probe_ns)  # noqa: S102 - our own constant source
run_local_probes = _probe_ns["run_probes"]

# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------
JWT = re.compile(r"eyJ[\w-]+\.eyJ[\w-]+\.[\w-]*")


def redact(text: str) -> str:
    return JWT.sub("<jwt>", text or "")[:300]


def classify(run: dict, success: list, blocked_statuses: list, kind: str = "http") -> tuple[str, str]:
    """Return (outcome, layer) for one attempt.

    allowed  the attack reached its goal (a success status, or the SQL ran);
    blocked  a control refused it, and `layer` names which one;
    inconclusive  anything else (for example a 404 or 500), reported as is.
    """
    status, body, error = run.get("status"), run.get("body") or "", run.get("error")
    if status in success:
        return ALLOWED, "-"
    if error:
        # SQL: the statement was refused. HTTP: the connection was refused,
        # reset or closed before any response (e.g. mTLS required).
        return BLOCKED, ("database" if kind == "sql" else "transport")
    if status in blocked_statuses:
        if status == 403 and body.startswith("RBAC: access denied"):
            return BLOCKED, "mesh"
        if status == 503:
            return BLOCKED, "fail-closed"
        return BLOCKED, "application"
    return INCONCLUSIVE, f"status {status}"


# --------------------------------------------------------------------------
# Cluster helpers
# --------------------------------------------------------------------------
class Cluster:
    def __init__(self, namespace: str) -> None:
        self.ns = namespace
        self.port_forward: subprocess.Popen | None = None

    def kubectl(self, *args: str, stdin: str | None = None, check: bool = True) -> str:
        result = subprocess.run(
            ["kubectl", "-n", self.ns, *args],
            input=stdin, capture_output=True, text=True, timeout=300,
        )
        if check and result.returncode != 0:
            raise RuntimeError(f"kubectl {' '.join(args[:3])} failed: {result.stderr.strip()[:300]}")
        return result.stdout

    def has(self, kind: str, name: str) -> bool:
        return bool(self.kubectl("get", kind, name, "--ignore-not-found", "-o", "name"))

    def exec_python(self, target: str, container: str, source: str, payload: dict) -> list:
        out = self.kubectl("exec", "-i", target, "-c", container, "--", "python", "-c", source,
                           stdin=json.dumps(payload))
        return json.loads(out.strip().splitlines()[-1])

    def secret_values(self) -> list[str]:
        """Every generated password in the namespace, used only to search logs."""
        data = json.loads(self.kubectl("get", "secrets", "-o", "json"))
        values = []
        for item in data["items"]:
            if item.get("type") != "Opaque":
                continue
            for key, value in (item.get("data") or {}).items():
                if key == "password":
                    values.append(base64.b64decode(value).decode())
        return values

    def start_frontend(self) -> str:
        self.port_forward = subprocess.Popen(
            ["kubectl", "-n", self.ns, "port-forward", "service/frontend", ":8000"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        line = self.port_forward.stdout.readline()
        match = re.search(r"127\.0\.0\.1:(\d+)", line)
        if not match:
            raise RuntimeError("could not port-forward to the frontend: " + line)
        return f"http://127.0.0.1:{match.group(1)}"

    def stop_frontend(self) -> None:
        if self.port_forward:
            self.port_forward.terminate()
            self.port_forward.wait(timeout=10)

    def deploy_attackers(self) -> None:
        image = self.kubectl("get", "deployment", "product",
                             "-o", "jsonpath={.spec.template.spec.containers[0].image}")
        manifest = ATTACKER_MANIFEST.read_text().replace("IMAGE", image)
        self.kubectl("apply", "-f", "-", stdin=manifest)
        self.kubectl("wait", "--for=condition=Ready", "pod", "-l", "role=security-test",
                     "--timeout=180s")

    def remove_attackers(self) -> None:
        self.kubectl("delete", "-f", "-", "--ignore-not-found", "--wait=false",
                     stdin=ATTACKER_MANIFEST.read_text().replace("IMAGE", "unused"), check=False)


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------
def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def jwt_parts(token: str) -> tuple[dict, dict, str]:
    header, payload, signature = token.split(".")
    pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
    return (json.loads(base64.urlsafe_b64decode(pad(header))),
            json.loads(base64.urlsafe_b64decode(pad(payload))), signature)


def forged_tokens(real: str) -> dict[str, str]:
    """Tokens an attacker can build without the identity provider's key."""
    header, claims, signature = jwt_parts(real)
    as_victim = dict(claims, preferred_username=VICTIM, sub="attacker-chosen")
    tampered = f"{b64url(json.dumps(header).encode())}.{b64url(json.dumps(as_victim).encode())}.{signature}"
    none_header = b64url(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    none_alg = f"{none_header}.{b64url(json.dumps(as_victim).encode())}."
    hs_header = b64url(json.dumps({"alg": "HS256", "typ": "JWT", "kid": header.get("kid")}).encode())
    hs_body = b64url(json.dumps(as_victim).encode())
    hs_sig = b64url(hmac.new(b"attacker-secret", f"{hs_header}.{hs_body}".encode(), hashlib.sha256).digest())
    return {"tampered": tampered, "none": none_alg, "hs256": f"{hs_header}.{hs_body}.{hs_sig}",
            "garbage": "not-a-jwt"}


def test_password() -> str:
    realm = json.loads((CHART / "files" / "ecommerce-realm.json").read_text())
    user = next(u for u in realm["users"] if u["username"] == USERNAME)
    return user["credentials"][0]["value"]


def login(base: str, password: str) -> str:
    [[run]] = run_local_probes([{"method": "POST", "url": f"{base}/api/login",
                                 "json": {"username": USERNAME, "password": password}}])
    if run["status"] != 200:
        raise RuntimeError(f"test user could not sign in: {run['status']} {redact(run['body'])}")
    return json.loads(run["body"])["access_token"]


WRONG_CLIENT_SRC = r'''
import json, os, sys, urllib.parse, urllib.request
creds = json.loads(sys.stdin.read())
body = urllib.parse.urlencode({"grant_type": "password", "client_id": "admin-cli",
    "username": creds["username"], "password": creds["password"]}).encode()
try:
    with urllib.request.urlopen(os.environ["KEYCLOAK_TOKEN_URL"], body, timeout=8) as r:
        print(json.dumps([json.loads(r.read())["access_token"]]))
except Exception as e:
    print(json.dumps([None]))
'''


def wrong_client_token(cluster: Cluster, password: str) -> str | None:
    """A genuine Keycloak token for the same user, issued to another client."""
    try:
        [token] = cluster.exec_python("deployment/frontend", "frontend", WRONG_CLIENT_SRC,
                                      {"username": USERNAME, "password": password})
        return token
    except RuntimeError:
        return None


# --------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------
BOTH_ALLOW = {"zero-trust": ALLOWED, "baseline": ALLOWED}
BOTH_BLOCK = {"zero-trust": BLOCKED, "baseline": BLOCKED}
ZT_BLOCKS = {"zero-trust": BLOCKED, "baseline": ALLOWED}
ZT_ONLY = {"zero-trust": BLOCKED, "baseline": NOT_APPLICABLE}

# Where workload attacks run: source -> (kubectl target, container).
SOURCES = {
    "product": ("deployment/product", "product"),
    "cart": ("deployment/cart", "cart"),
    "order": ("deployment/order", "order"),
    "attacker-no-mesh": ("pod/attacker-no-mesh", "attacker"),
    "attacker-mesh": ("pod/attacker-mesh", "attacker"),
}


def scenarios(base: str, token: str, tokens: dict, wrong_client: str | None) -> list[dict]:
    auth = lambda t: {"Authorization": f"Bearer {t}"}  # noqa: E731
    me, victim = f"{base}/api/cart/{USERNAME}", f"{base}/api/cart/{VICTIM}"
    s = [
        # Controls: the legitimate flow must keep working in both variants.
        dict(id="C-01", threat="-", source="external", expected=BOTH_ALLOW,
             title="Customer browses the catalog",
             probe=dict(url=f"{base}/api/products", headers=auth(token), success=[200])),
        dict(id="C-02", threat="-", source="external", expected=BOTH_ALLOW,
             title="Customer reads their own cart",
             probe=dict(url=me, headers=auth(token), success=[200])),
        dict(id="C-03", threat="-", source="cart", expected=BOTH_ALLOW,
             title="Cart service looks up a product price (allowed edge)",
             probe=dict(url="http://product:8000/products/p-001", success=[200])),
        # C-04 (full checkout) is run separately, once.

        # TM-01 compromised Product workload goes after payment data.
        dict(id="TM-01a", threat="TM-01", source="product", expected=ZT_BLOCKS,
             title="Compromised product creates a payment authorization",
             probe=dict(method="POST", url="http://payment:8000/authorizations",
                        json={"order_id": "attack-tm01", "customer_id": USERNAME,
                              "amount_cents": 1}, success=[201])),
        dict(id="TM-01b", threat="TM-01", source="product", expected=ZT_BLOCKS,
             title="Compromised product lists all payment authorizations",
             probe=dict(url="http://payment:8000/authorizations", success=[200])),
        dict(id="TM-01c", threat="TM-01", source="product", expected=ZT_BLOCKS,
             title="Compromised product reads payment table with its DB login",
             probe=dict(kind="sql", success=["ok"], sql=[
                 "SELECT * FROM svc_payment.payment_authorizations LIMIT 5",
                 "SELECT * FROM public.payment_authorizations LIMIT 5"])),

        # TM-02 inventory mutation outside the order workflow.
        dict(id="TM-02a", threat="TM-02", source="cart", expected=ZT_BLOCKS,
             title="Compromised cart reserves stock without an order",
             probe=dict(method="POST", url="http://inventory:8000/reservations",
                        json={"order_id": "attack-tm02",
                              "items": [{"product_id": "p-003", "quantity": 1}]},
                        success=[201],
                        cleanup={"method": "DELETE",
                                 "url": "http://inventory:8000/reservations/{id}"})),
        dict(id="TM-02b", threat="TM-02", source="product", expected=ZT_BLOCKS,
             title="Compromised product rewrites stock levels in the database",
             probe=dict(kind="sql", success=["ok"], sql=[
                 "UPDATE svc_inventory.inventory_stock SET available = available + 1000",
                 "UPDATE public.inventory_stock SET available = available + 1000"])),

        # TM-03 a signed-in customer changes the customer id (IDOR).
        dict(id="TM-03a", threat="TM-03", source="external", expected=ZT_BLOCKS,
             title="Customer reads another customer's cart",
             probe=dict(url=victim, headers=auth(token), success=[200])),
        dict(id="TM-03b", threat="TM-03", source="external", expected=ZT_BLOCKS,
             title="Customer adds an item to another customer's cart",
             probe=dict(method="PUT", url=f"{victim}/items", headers=auth(token),
                        json={"product_id": "p-001", "quantity": 1}, success=[200],
                        cleanup={"method": "DELETE", "url": f"{victim}/items/p-001"})),

        # TM-04 bad credentials. Authentication exists in both variants.
        dict(id="TM-04a", threat="TM-04", source="external", expected=BOTH_BLOCK,
             title="Request without a token",
             probe=dict(url=me, success=[200])),
        dict(id="TM-04b", threat="TM-04", source="external", expected=BOTH_BLOCK,
             title="Malformed token",
             probe=dict(url=me, headers=auth(tokens["garbage"]), success=[200])),
        dict(id="TM-04c", threat="TM-04", source="external", expected=BOTH_BLOCK,
             title="Real token with the username changed to the victim",
             probe=dict(url=victim, headers=auth(tokens["tampered"]), success=[200])),
        dict(id="TM-04d", threat="TM-04", source="external", expected=BOTH_BLOCK,
             title="Unsigned token (alg=none)",
             probe=dict(url=victim, headers=auth(tokens["none"]), success=[200])),
        dict(id="TM-04e", threat="TM-04", source="external", expected=BOTH_BLOCK,
             title="Token signed with an attacker-chosen HS256 key",
             probe=dict(url=victim, headers=auth(tokens["hs256"]), success=[200])),
    ]
    if wrong_client:
        s.append(dict(id="TM-04f", threat="TM-04", source="external", expected=BOTH_BLOCK,
                      title="Valid Keycloak token issued to another client (admin-cli)",
                      probe=dict(url=me, headers=auth(wrong_client), success=[200])))
    s += [
        # TM-05 workloads without a (trusted) identity.
        dict(id="TM-05a", threat="TM-05", source="attacker-no-mesh", expected=ZT_BLOCKS,
             title="Pod without mesh identity reads a customer cart",
             probe=dict(url=f"http://cart:8000/carts/{USERNAME}", success=[200])),
        dict(id="TM-05b", threat="TM-05", source="attacker-no-mesh", expected=ZT_BLOCKS,
             title="Pod without mesh identity lists payment authorizations",
             probe=dict(url="http://payment:8000/authorizations", success=[200])),
        dict(id="TM-05c", threat="TM-05", source="attacker-mesh", expected=ZT_BLOCKS,
             title="Pod with an untrusted mesh identity reads a customer cart",
             probe=dict(url=f"http://cart:8000/carts/{USERNAME}", success=[200])),

        # TM-06 allowed caller, disallowed method/route; control-plane access.
        dict(id="TM-06a", threat="TM-06", source="cart", expected=ZT_BLOCKS,
             title="Compromised cart lists a customer's orders (may only create)",
             probe=dict(url=f"http://order:8000/orders?customer_id={USERNAME}", success=[200])),
        dict(id="TM-06b", threat="TM-06", source="order", expected=ZT_BLOCKS,
             title="Compromised order lists payments (may only authorize)",
             probe=dict(url="http://payment:8000/authorizations", success=[200])),
        dict(id="TM-06c", threat="TM-06", source="product", expected=ZT_BLOCKS,
             title="Compromised product opens the Keycloak admin console",
             probe=dict(url="http://keycloak:8080/admin/master/console/", success=[200])),
        dict(id="TM-06d", threat="TM-06", source="product", expected=ZT_ONLY,
             title="Compromised product uploads a policy to OPA",
             probe=dict(method="PUT", url="http://opa:8181/v1/policies/attack",
                        data="package attack\n\nallow := true\n", success=[200],
                        cleanup={"method": "DELETE",
                                 "url": "http://opa:8181/v1/policies/attack"})),
    ]
    return s


# --------------------------------------------------------------------------
# Special scenarios
# --------------------------------------------------------------------------
def normal_checkout(base: str, token: str) -> dict:
    """C-04: a full checkout of one item, leaving the user's cart as it was."""
    headers = {"Authorization": f"Bearer {token}"}
    cart_url = f"{base}/api/cart/{USERNAME}"
    call = lambda method, url, **kw: run_local_probes(  # noqa: E731
        [dict(method=method, url=url, headers=headers, **kw)])[0][0]
    saved = json.loads(call("GET", cart_url)["body"]).get("items", [])
    for item in saved:
        call("DELETE", f"{cart_url}/items/{item['product_id']}")
    call("PUT", f"{cart_url}/items", json={"product_id": "p-002", "quantity": 1})
    result = call("POST", f"{cart_url}/checkout")
    if result["status"] != 201 and "p-002" not in {i["product_id"] for i in saved}:
        call("DELETE", f"{cart_url}/items/p-002")
    for item in saved:
        call("PUT", f"{cart_url}/items",
             json={"product_id": item["product_id"], "quantity": item["quantity"]})
    return result


def policy_engine_down(cluster: Cluster, base: str, token: str, repeat: int) -> list[dict]:
    """TM-07: stop OPA and check that protected requests fail closed."""
    cluster.kubectl("scale", "deployment/opa", "--replicas=0")
    try:
        cluster.kubectl("wait", "--for=delete", "pod", "-l", "app=opa", "--timeout=120s",
                        check=False)
        return run_local_probes([dict(url=f"{base}/api/cart/{USERNAME}", repeat=repeat,
                                      headers={"Authorization": f"Bearer {token}"},
                                      success=[200])])[0]
    finally:
        cluster.kubectl("scale", "deployment/opa", "--replicas=1")
        cluster.kubectl("rollout", "status", "deployment/opa", "--timeout=180s")


def log_scan(cluster: Cluster, secrets: list[str]) -> dict:
    """TM-09: search every container log in the namespace for credentials."""
    pods = cluster.kubectl("get", "pods", "-o", "jsonpath={.items[*].metadata.name}").split()
    findings = []
    for pod in pods:
        logs = cluster.kubectl("logs", pod, "--all-containers", "--tail=-1", check=False)
        found = Counter()
        found["jwt"] = len(JWT.findall(logs))
        found["bearer header"] = logs.count("Bearer ")
        found["password value"] = sum(logs.count(v) for v in secrets if len(v) >= 8)
        for kind, count in found.items():
            if count:
                findings.append({"pod": pod, "kind": kind, "count": count})
    return {"status": "clean" if not findings else "leak", "pods_scanned": len(pods),
            "findings": findings}


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------
def run_scenario_batch(cluster: Cluster, items: list[dict], repeat: int) -> None:
    by_source: dict[str, list[dict]] = {}
    for item in items:
        item["probe"].setdefault("repeat", repeat)
        by_source.setdefault(item["source"], []).append(item)
    for source, group in by_source.items():
        probes = [g["probe"] for g in group]
        if source == "external":
            results = run_local_probes(probes)
        else:
            target, container = SOURCES[source]
            results = cluster.exec_python(target, container, PROBE_SRC, {"probes": probes})
        for item, runs in zip(group, results):
            item["runs"] = runs


def summarize(item: dict, variant: str) -> dict:
    probe = item.get("probe") or {}
    runs = []
    for run in item.get("runs", []):
        outcome, layer = classify(run, probe.get("success", []),
                                  probe.get("blocked", [401, 403]), probe.get("kind", "http"))
        runs.append({"outcome": outcome, "layer": layer, "status": run.get("status"),
                     "error": redact(run.get("error") or ""), "ms": run.get("ms"),
                     "cleanup_status": run.get("cleanup_status"),
                     "body": redact(run.get("body", ""))})
    counts = Counter(r["outcome"] for r in runs)
    outcome = (next(iter(counts)) if len(counts) == 1 else "mixed") if runs else NOT_APPLICABLE
    return {"id": item["id"], "threat": item["threat"], "title": item["title"],
            "source": item["source"], "expected": item["expected"][variant],
            "outcome": outcome, "counts": dict(counts),
            "layers": dict(Counter(r["layer"] for r in runs if r["outcome"] == BLOCKED)),
            "runs": runs}


def environment(cluster: Cluster) -> dict:
    def sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.exists() else "-"

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "services", "deploy"],
                                cwd=ROOT, capture_output=True, text=True).stdout.strip())
    images = cluster.kubectl("get", "deployments", "-o",
                             "jsonpath={range .items[*]}{.metadata.name}={.spec.template.spec.containers[0].image} {end}")
    containers = cluster.kubectl("get", "pods", "-l", "app=cart", "-o",
                                 "jsonpath={.items[0].spec.containers[*].name} {.items[0].spec.initContainers[*].name}")
    return {
        "git_commit": commit + ("-dirty" if dirty else ""),
        "images": dict(pair.split("=", 1) for pair in images.split()),
        "istio_sidecar": "istio-proxy" in containers,
        "config_sha256": {
            "values.yaml": sha(CHART / "values.yaml"),
            "values-baseline.yaml": sha(CHART / "values-baseline.yaml"),
            "istio/security.yaml": sha(ROOT / "deploy" / "istio" / "security.yaml"),
            "ecommerce_authz.rego": sha(CHART / "files" / "policies" / "ecommerce_authz.rego"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--variant", required=True, choices=["zero-trust", "baseline"])
    parser.add_argument("--repeat", type=int, default=10, help="attempts per attack")
    parser.add_argument("--skip-disruptive", action="store_true",
                        help="do not stop OPA for TM-07")
    parser.add_argument("--include-expiry", action="store_true",
                        help="also replay a token after it expires (waits up to 5 minutes)")
    args = parser.parse_args()

    cluster = Cluster(args.namespace)
    started = datetime.now(timezone.utc)
    print(f"[{args.variant}] namespace {args.namespace}, {args.repeat} attempts per attack")
    password = test_password()
    try:
        print("  deploying attacker pods ...")
        cluster.deploy_attackers()
        base = cluster.start_frontend()
        token = login(base, password)
        items = scenarios(base, token, forged_tokens(token), wrong_client_token(cluster, password))
        has_opa = cluster.has("deployment", "opa")
        for item in items:
            item["skip"] = item["expected"][args.variant] == NOT_APPLICABLE
        print("  running attacks ...")
        run_scenario_batch(cluster, [i for i in items if not i.get("skip")], args.repeat)

        checkout = dict(id="C-04", threat="-", source="external", expected=BOTH_ALLOW,
                        title="Customer checks out their own cart (once per run)",
                        probe=dict(success=[201]), runs=[normal_checkout(base, token)])
        items.insert(3, checkout)

        tm07 = dict(id="TM-07", threat="TM-07", source="external", expected=ZT_ONLY,
                    title="Protected request while the policy engine is down",
                    probe=dict(success=[200], blocked=[401, 403, 503]))
        if has_opa and not args.skip_disruptive:
            print("  stopping OPA for TM-07 ...")
            tm07["runs"] = policy_engine_down(cluster, base, token, args.repeat)
        elif has_opa:
            tm07["expected"] = {v: NOT_APPLICABLE for v in tm07["expected"]}  # skipped on request
        items.append(tm07)

        if args.include_expiry:
            _, claims, _ = jwt_parts(token)
            wait = max(0, claims["exp"] - time.time() + 5)
            print(f"  waiting {wait:.0f}s for the token to expire ...")
            time.sleep(wait)
            expiry = dict(id="TM-04g", threat="TM-04", source="external", expected=BOTH_BLOCK,
                          title="Replay of an expired token",
                          probe=dict(url=f"{base}/api/cart/{USERNAME}", success=[200],
                                     headers={"Authorization": f"Bearer {token}"}))
            run_scenario_batch(cluster, [expiry], args.repeat)
            items.append(expiry)

        print("  scanning logs ...")
        scan = log_scan(cluster, cluster.secret_values() + [password, token])
        env = environment(cluster)
    finally:
        cluster.stop_frontend()
        cluster.remove_attackers()

    summary = [summarize(i, args.variant) for i in items]
    leak = {"id": "TM-09", "threat": "TM-09", "title": "Credentials or tokens in container logs",
            "source": "logs", "expected": BLOCKED,
            "outcome": BLOCKED if scan["status"] == "clean" else ALLOWED,
            "counts": {BLOCKED if scan["status"] == "clean" else ALLOWED: 1},
            "layers": {"logging": 1} if scan["status"] == "clean" else {}, "runs": [], "scan": scan}
    summary.append(leak)

    report = {"variant": args.variant, "namespace": args.namespace, "repeat": args.repeat,
              "started": started.isoformat(timespec="seconds"),
              "finished": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "environment": env, "scenarios": summary}
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{args.variant}-{started.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(report, indent=2))

    width = max(len(s["title"]) for s in summary)
    for s in summary:
        mark = "ok " if s["outcome"] == s["expected"] else "!! "
        layers = ",".join(s["layers"]) if s["layers"] else ""
        counts = " ".join(f"{k}={v}" for k, v in s["counts"].items())
        print(f"  {mark}{s['id']:<7}{s['title']:<{width}}  {s['outcome']:<12}{counts:<16}{layers}")
    unexpected = [s["id"] for s in summary if s["outcome"] != s["expected"]]
    print(f"  results: {path.relative_to(ROOT)}")
    print(f"  {len(summary) - len(unexpected)}/{len(summary)} scenarios as expected"
          + (f"; unexpected: {', '.join(unexpected)}" if unexpected else ""))
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(main())
