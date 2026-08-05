# Architecture Decision: Balanced Zero-Trust Track

**Status:** Provisional decision for implementation planning  
**Date:** 2026-07-28

## Decision

Use a local Kubernetes deployment as the target environment, with the following control layers:

| Layer | Selected direction | Purpose |
|---|---|---|
| Runtime | Kubernetes via `kind` or `k3d` | Reproducible cloud-native deployment |
| Service mesh | Istio | Service identity, mTLS, traffic policy, and enforcement points |
| User identity | Keycloak using OAuth2/OpenID Connect | Reproducible user authentication and token issuance |
| Workload authentication | Istio mesh identities and strict mTLS | Authenticate service-to-service connections |
| Coarse authorization | Istio authorization policies | Restrict which workloads may reach which routes |
| Domain authorization | OPA/Rego, called from an enforcement layer | Apply action, resource-owner, role, and context rules |
| Application protocol | REST/JSON initially | Keep service interactions easy to inspect and test |
| Persistence | PostgreSQL with service-specific credentials and logical ownership | Demonstrate data isolation without excessive local infrastructure |
| Payment | Mock or sandbox provider | Avoid real card data and production payment scope |
| Observability | OpenTelemetry with metrics and traces | Correlate identities, policy decisions, failures, and latency |

The implementation language remains open. It should be chosen based on the developer's existing proficiency and the quality of its HTTP, OIDC, testing, and observability libraries.

## Intended topology

```text
Customer / Administrator
          |
     Ingress/API gateway
          |
  Keycloak token validation
          |
  Istio enforcement point
          |
  +-------+--------+--------+---------+-------------+
  | Product       Cart     Order     Inventory     Payment
  |                          |           |             |
  |                          +-----------+-------------+
  |                                      |
  +----------------------------- Notification

Every service-to-service edge is authenticated with mTLS and evaluated against an explicit allow policy.
Business-level decisions (for example, whether a customer owns an order) are evaluated separately from network reachability.
Telemetry is emitted at ingress, enforcement, and service layers.
```

The diagram is conceptual. The final design must show the actual data stores, ingress path, policy decision point, and telemetry pipeline.

## Why this track

- Kubernetes makes workload identity, service boundaries, and deployment assumptions visible in the thesis.
- Istio provides a single place to demonstrate strict mTLS and service-level authorization without rewriting every HTTP client.
- Keycloak avoids building an identity provider while keeping user flows reproducible locally.
- OPA/Rego allows business authorization to be expressed as versioned policy rather than scattered conditionals.
- REST/JSON keeps request traces and attack scenarios straightforward to inspect.
- A mock payment provider keeps the demonstrator safely outside real card-data handling.
- OpenTelemetry makes the security and performance evaluation observable.

## Baseline for evaluation

The baseline must use the same business services, deployment resources, test data, and traffic generator. Only the security controls should differ:

1. **Baseline variant:** authenticated edge where needed, but no strict service mTLS and no least-privilege service policy; internal reachability represents the traditional implicit-trust model.
2. **Zero-Trust variant:** strict mTLS, workload-aware authorization, OPA/Rego domain checks, and security telemetry.

This allows the evaluation to separate security behavior from unrelated changes in application logic or infrastructure.

## Deliberately deferred choices

- **SPIRE:** keep as a stretch goal or comparison. Add it only after the core Istio-based implementation and evaluation are stable. Introducing both a mesh identity system and SPIRE at the beginning would make failures harder to attribute.
- **Linkerd:** retain as a documented alternative, but do not run two meshes in the same implementation.
- **Asynchronous messaging:** start with synchronous REST calls. Add an event broker only if notification/order workflows require it or if it becomes part of the research question.
- **Cloud deployment:** not required for the thesis demonstrator unless the advisor explicitly requests it.

## Implementation gates

1. Deploy one unsecured service and one protected health endpoint in Kubernetes.
2. Add the complete service skeleton and a working shopping flow without Zero-Trust controls.
3. Add Keycloak and validate user tokens at the edge.
4. Enable strict Istio mTLS and prove that service identity is visible to policy.
5. Add default-deny service policies and implement the authorization matrix.
6. Add OPA/Rego for ownership and action-level decisions.
7. Add telemetry, fault cases, attack tests, and the baseline comparison.

Each gate should leave a runnable state and a short record of what was verified.

## Risks

- Local Kubernetes and Istio may consume more resources than a small laptop comfortably provides.
- Mesh policy can prove that a caller is a particular workload but cannot by itself decide all resource-ownership rules; application or OPA checks remain necessary.
- A service mesh can hide network mechanics from the application, so the thesis must document enforcement points and include negative tests.
- Comparing a baseline with controls disabled must avoid accidentally leaving policy or mTLS enabled.

