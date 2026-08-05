# Zero-Trust E-commerce Platform

## 1. Purpose and current scope

This project is a master's-thesis demonstrator for applying Zero-Trust Architecture to a containerized microservices application. The e-commerce domain is used because it combines public APIs, sensitive personal data, a payment boundary, and several service-to-service interactions in one manageable scenario.

The demonstrator is not intended to be a production payment platform. Its purpose is to make security decisions explicit, enforce least privilege between services, and measure the security and performance consequences of those controls.

The current phase is design-first. No implementation claim should be made until the corresponding behavior is deployed and tested.

## 2. Research question

**How can Zero-Trust principles be applied to a containerized e-commerce microservices platform so that unauthorized service-to-service access and lateral movement are prevented, while the resulting security controls remain observable and impose measurable, acceptable overhead?**

## 3. Intended contribution

The thesis should deliver:

1. A threat-informed Zero-Trust architecture for a small e-commerce microservices system.
2. An explicit mapping from identities and request context to least-privilege authorization decisions.
3. A reproducible implementation of the selected controls, including service identity, authenticated service communication, policy enforcement, and security telemetry.
4. An evaluation against a minimally secured baseline using repeatable attack scenarios and performance measurements.

## 4. System boundary

### In scope

- Product browsing and retrieval.
- Shopping cart operations.
- Order creation and order-status retrieval.
- Inventory reservation and release.
- Payment authorization through a mock or sandbox payment provider.
- Notification of relevant order events.
- User and workload identity verification.
- Service-to-service authentication and authorization.
- Audit logging, metrics, and distributed tracing for security-relevant events.
- Containerized deployment and a reproducible local or lab environment.

### Out of scope for the first implementation

- Handling real card numbers or production payment credentials.
- Building a full customer identity product or an enterprise IAM service from scratch.
- Multi-region availability, disaster recovery, and production-scale capacity planning.
- Proving protection against every OWASP or STRIDE category.
- Replacing the underlying operating system, container runtime, or orchestrator security model.

## 5. Actors and trust assumptions

| Actor | Description | Initial trust assumption |
|---|---|---|
| Customer | Uses the public shopping API | Untrusted until authenticated where required |
| Administrator/operator | Manages products, inventory, and platform operations | Authenticated but still least-privilege |
| External payment provider | Sandbox or mock dependency | External; never implicitly trusted |
| Platform operator | Runs the container/orchestration environment | Privileged operational role, audited |
| Service workload | Product, Cart, Order, Payment, Inventory, or Notification process | No implicit trust; must present workload identity |
| Attacker | May possess credentials, compromise a workload, or send crafted requests | Assume breach and attempt lateral movement |

## 6. Functional requirements

| ID | Requirement | Acceptance indication |
|---|---|---|
| FR-01 | A customer can browse products and retrieve product details. | Valid requests return product data; malformed/unauthorized requests are rejected according to policy. |
| FR-02 | A customer can create, update, and view their cart. | Cart ownership is enforced; one customer cannot read another customer’s cart. |
| FR-03 | A customer can create an order from an eligible cart. | The order records its owner and requested items; invalid inventory state is rejected. |
| FR-04 | The platform can reserve and release inventory for an order. | Only the authorized order workflow can invoke inventory mutations. |
| FR-05 | The platform can authorize a payment using a mock or sandbox provider. | Payment authorization is isolated and produces an auditable outcome. |
| FR-06 | The platform can publish order events and send notifications. | Notification receives only the fields required for its purpose. |
| FR-07 | A user or workload request is authenticated before protected access. | Missing, expired, invalid, or wrong-audience credentials are rejected. |
| FR-08 | Every service-to-service call is authenticated and authorized independently. | Network reachability alone never grants access. |
| FR-09 | Security decisions and relevant failures are observable. | Logs, metrics, and traces correlate the request, identity, policy result, and outcome without exposing secrets. |

## 7. Security and quality requirements

| ID | Requirement | Evaluation target |
|---|---|---|
| SEC-01 | No service is trusted solely because it is on an internal network. | Unauthorized lateral-call scenarios are denied. |
| SEC-02 | Workloads use short-lived, verifiable identities. | Invalid, expired, revoked, or wrong-service identities fail authentication. |
| SEC-03 | Authorization follows least privilege and default deny. | A policy matrix shows only required caller-to-resource paths are allowed. |
| SEC-04 | Sensitive data is minimized and protected in transit. | Payment data is mocked/tokenized; protected traffic uses authenticated encryption. |
| SEC-05 | Administrative operations are separately authorized and auditable. | Non-administrative identities cannot perform operator actions. |
| SEC-06 | Policy and identity failures fail closed. | Dependency or policy errors do not silently become allow decisions. |
| SEC-07 | Security events are tamper-evident enough for the demonstrator’s scope. | Each event has timestamp, request correlation, actor identity, action, resource, decision, and reason. |
| NFR-01 | The environment is reproducible. | A clean setup can deploy the same version and run the test scenarios. |
| NFR-02 | Performance overhead is measurable. | Latency, throughput, and resource use are measured with and without Zero-Trust controls. |
| NFR-03 | The design is explainable. | Every control maps to a threat, requirement, or Zero-Trust principle. |
| NFR-04 | Secrets are not committed to the repository or emitted in normal logs. | Repository and log review finds no live credentials or payment data. |

## 8. Initial service responsibilities

| Service | Owns or exposes | Must not do by default |
|---|---|---|
| Product | Product catalog read operations | Mutate orders, inventory, or payments |
| Cart | Customer cart state | Authorize payment or mutate inventory directly |
| Order | Order lifecycle and orchestration | Read another customer’s order without authorization |
| Payment | Payment authorization result and provider integration | Expose raw payment credentials or act as a general data store |
| Inventory | Stock availability and reservation | Accept arbitrary customer-facing mutations |
| Notification | Delivery of order-related notifications | Read full customer/payment records |

An API gateway, identity provider, policy decision point, policy enforcement points, telemetry pipeline, and deployment platform are architectural components rather than business services. Their exact technologies remain open until the architecture decision phase.

## 9. Success criteria

The project is successful when it can demonstrate all of the following:

- The normal shopping flow works end to end in the reproducible environment.
- A compromised or misbehaving service cannot invoke operations outside its policy.
- Forged, expired, or incorrectly scoped credentials are rejected.
- Security decisions are visible in correlated telemetry.
- The thesis reports measured overhead against a clearly defined baseline, with test conditions and limitations.

## 10. Open decisions to resolve before implementation

1. Target deployment: local containers, Kubernetes, or both.
2. Workload identity approach: SPIFFE/SPIRE, service-mesh identity, or a deliberately smaller equivalent.
3. Policy engine and enforcement placement: OPA/Rego, mesh policy, application middleware, or a combination.
4. User identity provider and token format.
5. Synchronous versus event-driven communication for order and notification flows.
6. Baseline definition and performance test tooling.
7. Advisor-approved thesis template, citation style, and final submission constraints.

