# EcommerceZTA

Planning artifacts for the Zero-Trust E-commerce Platform master's thesis.

## Current status

The project has completed the initial requirements and threat-model phase. The provisional implementation direction is the balanced Zero-Trust track: local Kubernetes, Istio, Keycloak, OPA/Rego, PostgreSQL, and OpenTelemetry.

The implementation language is Python/FastAPI. The baseline includes deterministic Product, Cart, Order, Inventory, Payment, and Notification services with health checks, contract tests, container image definitions, and Kubernetes manifests. The Helm deployment includes PostgreSQL and a local Keycloak realm; all six business services can use PostgreSQL, while the frontend enforces Keycloak login and cart ownership for the browser flow.

- [Scope and requirements](docs/01-scope-and-requirements.md)
- [Threat model](docs/02-threat-model.md)
- [Architecture decision](docs/03-architecture-decision.md)
- [Service contracts and authorization design](docs/04-service-contracts-and-policies.md)
- [Observability and evaluation design](docs/05-observability-and-evaluation-design.md)
- [Implementation plan](docs/06-implementation-plan.md)

## M0 quick start

```bash
make install
make test
make run-product
```

Then open `http://127.0.0.1:8000/docs` or query `http://127.0.0.1:8000/products`.

To build and deploy the current baseline services:

```bash
make build-services
make k8s-deploy
```

The same baseline, plus a small browser frontend, is also packaged as a Helm chart. Render it
without changing the cluster, or install/upgrade it in the active local
Kubernetes context:

```bash
make helm-template
make helm-deploy
```

## Authorization policy

The frontend validates Keycloak access tokens and asks Open Policy Agent (OPA)
whether each protected action is allowed. The deployed policy permits customers
to read the catalog and access only their own cart; support and admin roles have
the additional access described in
[`ecommerce_authz.rego`](deploy/helm/ecommerce-platform/files/policies/ecommerce_authz.rego).
OPA failures are treated as denials, so authorization fails closed.

Run the policy tests without changing the cluster:

```bash
make test-opa
```

Changing the policy and running `make helm-deploy` updates the ConfigMap and
rolls the OPA pod automatically.

## Zero-Trust hardening

- **Mesh:** strict mTLS plus default-deny Istio policies that allow only named
  operations (caller + method + route). See [the Istio guide](deploy/istio/README.md).
- **OPA API:** only the decision endpoint and `/health` are reachable, both
  through the mesh and through OPA's own `system.authz` policy.
- **Data plane:** each service uses its own PostgreSQL role and schema.
- **Credentials:** generated per deployment into Kubernetes Secrets. None are
  kept in `values.yaml`.

Apply the mesh policy before the chart, so the database bootstrap Job can
reach PostgreSQL:

```bash
make istio-policies
make helm-deploy
```

`make test` includes static checks of the mesh policy matrix and of the Helm
values, so neither needs a cluster.

## Kubernetes

Kubernetes support is configured for Docker Desktop's managed kind-mode cluster. See [the Kubernetes guide](deploy/kubernetes/README.md), or run:

```bash
make k8s-deploy
make k8s-status
make k8s-product
```
- Source outline: [Semester 2 annotated table of contents](Cuprins_Semestrul_2.pdf)
- Source draft: [Dissertation draft](Disertatie.pdf)
