# Threat Model

## 1. Method and security posture

This is a focused, thesis-scale threat model. It uses an assume-breach posture: an attacker may already control a credential, a client session, or one service workload. The model therefore treats network location and successful first-hop access as insufficient evidence of trust.

The model covers the demonstrator’s high-value assets, request paths, identity and policy controls, and the attack scenarios used for evaluation. It is not a claim of complete coverage of all production threats.

## 2. Protected assets

| Asset | Why it matters | Required protection |
|---|---|---|
| Customer identity and profile data | Privacy and account integrity | Authentication, authorization, minimization, auditability |
| Credentials, tokens, and workload keys | Can enable impersonation or lateral movement | Short lifetime, protected storage, rotation, no logging |
| Cart and order data | Customer privacy and transaction integrity | Ownership checks, least privilege, integrity/audit trail |
| Inventory state | Business correctness and availability | Authorized mutations, concurrency control, audit events |
| Payment authorization data | Financial and compliance sensitivity | Mock/tokenized data, strict isolation, encryption, minimal retention |
| Authorization policies | Define the security boundary | Version control, review, default deny, tested changes |
| Service identity authority | Can mint or validate workload identities | Strong administrative protection and auditability |
| Security telemetry | Needed for detection and thesis evaluation | Correlation, access control, retention, secret redaction |
| Images, manifests, and configuration | Supply-chain and deployment integrity | Review, provenance, scanning, controlled release |

## 3. Trust boundaries

1. **Public-client boundary:** customer or attacker traffic enters through the public API surface.
2. **Identity boundary:** user tokens and workload identities are issued or validated by identity infrastructure.
3. **Service boundary:** each microservice is a separate security principal; an internal route is not a trust grant.
4. **Payment boundary:** the Payment service communicates with an external sandbox/mock provider.
5. **Control-plane boundary:** deployment, identity, policy, and telemetry administration is separate from business traffic.
6. **Data boundary:** service-owned data stores are isolated by authorization and, where practical, by separate credentials.

## 4. Attacker capabilities

The evaluation attacker may:

- Send arbitrary public API requests and replay or modify requests.
- Present missing, expired, forged, wrong-audience, or wrong-role credentials.
- Obtain a valid low-privilege customer credential.
- Compromise one non-control-plane service and issue calls using that service’s runtime context.
- Attempt direct calls to internal endpoints if network routing permits them.
- Abuse input fields to trigger unauthorized data access or workflow transitions.
- Observe responses and timing, but not protected server-side secrets unless a scenario explicitly tests leakage.

The attacker is not assumed to have unrestricted host-root or identity-authority access. Those would be separate infrastructure threats beyond this demonstrator’s primary claim.

## 5. Primary abuse cases

| ID | Abuse case | Asset at risk | Expected control |
|---|---|---|---|
| TM-01 | A compromised Product workload calls Payment directly. | Payment data and transaction integrity | Workload identity plus default-deny authorization |
| TM-02 | A compromised Cart workload mutates Inventory without an Order workflow. | Inventory correctness | Caller/service and action-level policy |
| TM-03 | A customer changes an order or cart identifier to access another customer’s data. | Privacy and integrity | Resource ownership authorization |
| TM-04 | An attacker replays an expired or wrong-audience token. | Protected APIs | Token validation, lifetime, audience and issuer checks |
| TM-05 | A forged or mismatched workload certificate is presented. | Service identity | Mutual authentication and trust-domain validation |
| TM-06 | A service calls an allowed endpoint with a disallowed method or payload. | Business workflow integrity | Method, route, action, and context policy |
| TM-07 | A policy engine or identity dependency fails. | All protected operations | Fail-closed behavior and visible failure telemetry |
| TM-08 | Notification receives more customer/payment data than necessary. | Privacy | Data minimization and service-specific contract |
| TM-09 | Logs expose tokens, credentials, or payment values. | Credentials and payment data | Secret redaction, structured logging review |
| TM-10 | A vulnerable service image or configuration is deployed. | Platform and all downstream assets | Image/configuration review and reproducible release process |

## 6. Required authorization matrix (initial)

`D` means deny by default; `A` means an explicitly justified allow path must be defined before implementation.

| Caller → target | Product | Cart | Order | Inventory | Payment | Notification |
|---|---:|---:|---:|---:|---:|---:|
| Customer/API | A (read) | A (own cart) | A (own orders) | D | D | D |
| Product | D | D | D | D | D | D |
| Cart | A (read) | A (own cart) | A (create request) | D | D | D |
| Order | A (read) | A (read eligible cart) | A (own workflow) | A (reserve/release) | A (authorize) | A (publish event) |
| Inventory | D | D | A (reservation result/event only) | A (own state) | D | D |
| Payment | D | D | A (payment result callback/event only) | D | A (provider operation) | D |
| Notification | D | D | A (minimal event payload) | D | D | A (delivery) |
| Administrator | A (admin scope) | D or A (support scope) | A (admin scope) | A (admin scope) | D or A (audited support scope) | A (admin scope) |

This matrix is a design baseline, not yet a final policy file. Each `A` entry must become a named operation with an identity, resource scope, allowed method, and test case.

## 7. Evaluation scenarios

The implementation should include repeatable tests for at least:

1. Normal browse → cart → order → inventory → payment → notification flow.
2. Product → Payment direct lateral call.
3. Cart → Inventory direct mutation attempt.
4. Customer A reading or modifying Customer B’s cart/order.
5. Expired, forged, wrong-audience, and wrong-role credentials.
6. Invalid workload identity or certificate mismatch.
7. Policy/identity dependency unavailable during a protected request.
8. Log inspection for token, key, and payment-data leakage.

For every scenario, record the request identity, target operation, expected decision, observed decision, response, relevant policy version, and telemetry correlation ID.

## 8. Residual risks and limitations

- A compromised host, orchestrator control plane, or identity authority is outside the main demonstrator claim.
- The mock payment integration cannot establish production PCI-DSS compliance.
- A small local deployment cannot prove behavior under enterprise-scale load.
- Detection quality depends on telemetry retention and the scope of the test traffic.
- Application-level authorization cannot compensate for an untrusted build or deployment pipeline; supply-chain controls remain a supporting concern.

