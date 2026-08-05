# Implementation Plan

The implementation is staged so every milestone produces a runnable and testable result. Security controls are added incrementally rather than introduced as one opaque infrastructure change.

## 1. Proposed repository layout

```text
services/
  product/
  cart/
  order/
  inventory/
  payment/
  notification/
platform/
  kubernetes/
  istio/
  identity/
  opa/
  observability/
tests/
  contract/
  security/
  performance/
docs/
```

The exact language and framework can be selected before creating the service directories. The service boundaries and policy operation names should not depend on that choice.

## 2. Milestones

### M0 — Toolchain and skeleton

Deliver a health-check endpoint, local build instructions, formatting/linting, and a basic test command. Verify the chosen language, container image, and Kubernetes tooling on a clean checkout.

**Done when:** one service can be built, started, queried, and tested from documented commands.

### M1 — Unsecured business baseline

Implement the smallest end-to-end flow:

```text
catalog read → cart update → order create → inventory reserve
                                      └────→ payment authorize
                                      └────→ notification publish
```

Use deterministic seed data and a mock payment result. Keep business logic intentionally simple; this is the comparison baseline, not the product goal.

**Done when:** the normal flow and basic business-invalid cases work in containers and Kubernetes.

### M2 — User identity

Add Keycloak, configure a test realm/client, validate user tokens at the ingress path, and connect customer identity to cart/order ownership checks.

**Done when:** missing, expired, wrong-issuer, and wrong-audience tokens are rejected, while a valid customer can complete the normal flow.

### M3 — Workload identity and mTLS

Enable Istio injection and strict mTLS for the business namespace. Confirm that a service can identify its caller through mesh metadata and that non-meshed or invalid traffic is rejected.

**Done when:** a transport-level identity failure is distinct from an application-level policy denial in logs and tests.

### M4 — Default-deny service authorization

Translate the service matrix into explicit Istio policies. Permit only named routes and caller identities required by the normal flow.

**Done when:** Product → Payment and Cart → Inventory direct attempts are blocked, while Order’s authorized calls still succeed.

### M5 — Domain authorization with OPA/Rego

Add normalized policy input and decision handling for ownership, operation, role, and workflow context. Add policy unit tests before connecting the policy decision point to live requests.

**Done when:** customer ownership and service-action policies are tested independently and in end-to-end requests.

### M6 — Observability and evaluation harness

Add structured security events, traces, metrics, request generation, attack scenarios, and repeatable baseline/Zero-Trust runs.

**Done when:** a clean environment can produce the evidence tables and raw result files described in the evaluation design.

## 3. First implementation slice

The first coding slice should contain only:

- Product service with deterministic catalog data.
- Cart service with one customer-owned cart.
- Order service with an in-memory or simple persistent order record.
- A minimal API gateway or ingress route.
- Container build and a single Kubernetes deployment.
- Health/readiness probes and one contract test.

Do not begin with all six services, the full mesh, or production-like payment behavior. The purpose of M0 is to validate the toolchain and the service boundary with minimal debugging surface.

## 4. Definition of reproducibility

A new environment should be able to:

1. Install only documented prerequisites.
2. Build pinned images from the repository.
3. Start the selected local Kubernetes cluster.
4. Apply manifests in a documented order.
5. Seed deterministic test data.
6. Run normal-flow, security, and performance tests.
7. Collect results into a known output directory.

Commands should be non-interactive where possible, and every external dependency should have a health check and a documented version.

## 5. Baseline safeguards

The baseline must be clearly labeled and isolated from the secure variant. Do not delete secure policies to create a baseline; use separate manifests or an explicit, reviewable profile. This prevents an accidental permissive configuration from being mistaken for the evaluated Zero-Trust result.

## 6. Practical exit criteria before full implementation

Before expanding beyond M1, confirm:

- The advisor accepts the research question and selected demonstrator scope.
- The target local Kubernetes workflow runs on the available development machine.
- The six service boundaries are still justified by the use cases.
- The baseline traffic mix and attack scenarios can be automated.
- The chosen language has reliable OIDC, HTTP, testing, and telemetry support.

