# Istio Zero Trust controls

The current cluster uses Istio sidecar mode in the existing `default`
namespace. The namespace is retained for now so the live PostgreSQL PVC and
Helm release are not disrupted during the security migration.

## Enable the mesh

Istio 1.30.3 is installed with the default profile. Label the namespace and
restart the workloads so every pod receives an Envoy sidecar:

```bash
kubectl label namespace default istio-injection=enabled --overwrite
kubectl rollout restart deployment
kubectl rollout status deployment --all --timeout=180s
```

Apply strict mTLS and the least-privilege service policy:

```bash
kubectl apply -f deploy/istio/security.yaml
```

Use `make istio-policies`: it also deletes policies that older versions of
this file created under different names. ALLOW policies are OR-ed, so a stale
broad policy would otherwise silently keep granting access.

Each allowed edge is a named operation: caller identity + method + route
(`{*}` matches one path segment):

```text
frontend → product       GET    /products
cart     → product       GET    /products/{*}
frontend → cart          GET    /carts/{*}
                         PUT    /carts/{*}/items
                         DELETE /carts/{*}/items/{*}
                         POST   /carts/{*}/checkout
cart     → order         POST   /orders, /orders/{*}/reserve, /orders/{*}/confirm
order    → inventory     POST   /reservations;  DELETE /reservations/{*}
order    → payment       POST   /authorizations
order    → notification  POST   /events/order
frontend → keycloak      POST   .../openid-connect/token;  GET .../openid-connect/certs
frontend → opa           POST   /v1/data/ecommerce/authz/decision
database ← product, cart, order, inventory, payment, notification, db-bootstrap (TCP 5432)
```

Health probes are allowed (GET only). All other inbound traffic is denied by
the namespace default-deny policy. `tests/policy/test_istio_policies.py` pins
this matrix, so widening access requires an explicit test change.

Defence in depth behind the mesh:

- OPA runs with `--authorization=basic`; `files/policies/system_authz.rego`
  denies every call to its REST API except the decision endpoint and `/health`.
- PostgreSQL is TCP, so the mesh only checks caller identity. Each service
  connects as its own role (`svc_<name>`) that can only use its own schema.
  The Helm `db-bootstrap` Job creates the roles and schemas, using generated
  passwords from Kubernetes Secrets.

## Verify

```bash
kubectl get pods -o custom-columns='NAME:.metadata.name,READY:.status.containerStatuses[*].ready'
istioctl proxy-status
istioctl analyze -n default
```

The expected pod readiness is `2/2` for mesh-injected application pods.

## PostgreSQL mTLS

PostgreSQL is TCP traffic, so `security.yaml` includes a destination rule that
explicitly uses `ISTIO_MUTUAL` for `postgres.default.svc.cluster.local`. This
complements namespace-wide strict mTLS and lets the database policy identify
the calling workload service account.

If a long-running local cluster leaves a workload certificate expired, recreate
only the affected pod; Kubernetes preserves the PostgreSQL persistent volume:

```bash
kubectl delete pod -l app=postgres
kubectl rollout status deployment/postgres --timeout=180s
```
