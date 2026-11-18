# Security attack suite

Runs the evaluation scenarios from `docs/02-threat-model.md` (section 7)
against a deployed variant, then compares the baseline with the Zero-Trust
variant (`docs/05-observability-and-evaluation-design.md`, section 6).

## Variants

| | Zero-Trust (`default`) | Baseline (`ecommerce-baseline`) |
|---|---|---|
| Deploy | `make helm-deploy` + `make istio-policies` | `make baseline-deploy` |
| Service-to-service traffic | Istio STRICT mTLS, default-deny, one policy per route | Plain HTTP, any pod may call any route |
| User sign-in (Keycloak) | Yes | Yes |
| Ownership / role checks (OPA) | Yes, fail-closed | No: any signed-in user may act on any `customer_id` |
| Database login | One role and schema per service | One shared admin login |

Both use the same chart, images, seed data and resource limits. The only
differences are in `deploy/helm/ecommerce-platform/values-baseline.yaml` and
the namespace's `istio-injection=disabled` label.

## Running

```bash
make security-test              # both variants + comparison, 10 attempts each
make security-test REPEAT=30
```

Or one variant at a time:

```bash
python3 tests/security/run_attacks.py --namespace default --variant zero-trust --include-expiry
python3 tests/security/run_attacks.py --namespace ecommerce-baseline --variant baseline --include-expiry
python3 tests/security/compare.py
```

- `--include-expiry` adds TM-04g (replay of an expired token). It waits up to 5 minutes for the token to expire.
- `--skip-disruptive` skips TM-07. Otherwise the suite stops OPA for about 30 seconds to check that requests fail closed, then restores it.

Results go to `results/security/<variant>-<timestamp>.json`, and the comparison
goes to `results/security/summary.md`. Response bodies are truncated and
tokens are redacted, and no password or token is ever printed.

## Where attacks come from

- **external**: the test customer (`customer-1`, a valid low-privilege account) through a port-forward to the frontend.
- **product / cart / order**: code running inside that service's pod (`kubectl exec`), i.e. a compromised workload with that service's identity and database login.
- **attacker-no-mesh / attacker-mesh**: temporary pods from `attacker.yaml`. One has no mesh identity; the other has an identity that no policy trusts. Both are deleted after the run.

## Outcomes

Each attempt is recorded as `allowed` (the attack reached its goal), `blocked`
or `inconclusive`. A blocked attempt also records the layer that stopped it:

| Layer | Evidence |
|---|---|
| `mesh` | Envoy `403 RBAC: access denied` |
| `transport` | connection reset or refused (no mTLS identity) |
| `application` | 401/403 from the frontend (token check or OPA decision) |
| `database` | PostgreSQL `permission denied` |
| `fail-closed` | 503 while the policy engine is down |
| `logging` | log scan found no tokens or passwords |

## Side effects

Each run makes one real order for `customer-1` (C-04, one unit of p-002) and
puts the user's cart back as it was.

In the baseline, the attacks that succeed also leave records behind:

- payment authorizations for `attack-tm01`;
- reservations, which are released straight away;
- SQL writes, which are always rolled back.

## Not covered

- TM-08 (data minimisation) and TM-10 (supply chain) are design or process checks, not runtime attacks.
- Forging a workload certificate is approximated by a pod with no identity and a pod with an untrusted identity (TM-05).
