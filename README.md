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

## Kubernetes

Kubernetes support is configured for Docker Desktop's managed kind-mode cluster. See [the Kubernetes guide](deploy/kubernetes/README.md), or run:

```bash
make k8s-deploy
make k8s-status
make k8s-product
```
- Source outline: [Semester 2 annotated table of contents](Cuprins_Semestrul_2.pdf)
- Source draft: [Dissertation draft](Disertatie.pdf)
