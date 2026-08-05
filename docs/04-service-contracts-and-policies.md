# Service Contracts and Authorization Design

This document turns the threat-model matrix into named operations. It is still design-level: request schemas and policy examples are deliberately small enough to implement and test, but are not production API specifications.

## 1. Common request conventions

- JSON over HTTP for the first implementation.
- Every protected request carries a request correlation ID, generated at the edge when absent.
- User-facing requests carry an OIDC access token. Service calls carry the caller's workload identity through the mesh and may carry a narrowly scoped delegation or user context where the workflow requires it.
- Services authorize the action they are about to perform; they do not treat an upstream decision as permanent permission.
- Errors avoid revealing whether a protected resource exists when the caller is not authorized to know that fact.
- Idempotency keys are required for order creation and payment authorization retries.

## 2. Service operations

| Service | Operation | Caller(s) | Resource scope | Initial decision |
|---|---|---|---|---|
| Product | `GET /products`, `GET /products/{id}` | Customer/API, Cart, Order | Public catalog | Allow read; deny mutations to these callers |
| Product | `POST/PUT/DELETE /products/{id}` | Administrator | Product administration | Allow only audited admin scope |
| Cart | `GET /carts/{customerId}` | Customer/API, Order | Matching customer identity | Allow owner; Order gets only workflow-required view |
| Cart | `PUT /carts/{customerId}/items` | Customer/API | Matching customer identity | Allow owner |
| Cart | `POST /carts/{customerId}/checkout` | Customer/API | Matching customer identity | Allow owner; creates an Order request |
| Order | `POST /orders` | Cart/API | Customer and cart from request | Allow validated checkout workflow |
| Order | `GET /orders/{id}` | Customer/API, Administrator | Order owner or audited admin scope | Allow owner/admin; deny other customers |
| Order | `POST /orders/{id}/reserve` | Order workflow | Specific order | Internal allow only |
| Inventory | `POST /reservations` | Order | SKU and order reference | Allow Order identity only |
| Inventory | `DELETE /reservations/{id}` | Order | Reservation reference | Allow Order identity only |
| Payment | `POST /authorizations` | Order | Order/payment reference | Allow Order identity only; no customer direct access |
| Payment | `POST /provider/authorize` | Payment | External provider request | Allow Payment workload only |
| Notification | `POST /events/order` | Order | Minimal order event | Allow Order identity only |
| Notification | `POST /deliveries` | Notification | Delivery record | Internal service operation |

The exact route names may change with the implementation language, but the operation identity and authorization semantics should remain stable.

## 3. Authorization input model

The policy decision point receives a normalized request document. It should contain only data required for the decision:

```json
{
  "subject": {
    "kind": "workload",
    "id": "order",
    "user_id": "customer-123",
    "roles": ["checkout"]
  },
  "action": "payment.authorize",
  "resource": {
    "type": "payment",
    "order_id": "order-456",
    "owner_id": "customer-123"
  },
  "request": {
    "method": "POST",
    "route": "/authorizations",
    "request_id": "req-789"
  },
  "context": {
    "issuer": "https://identity.local",
    "audience": "payment",
    "m_tls": true
  }
}
```

The enforcement layer must derive the workload identity from authenticated connection metadata, not from an untrusted request header. User context must be validated before it is included in a policy input.

## 4. Policy rules

The initial policy semantics are:

1. Deny by default.
2. Require a valid workload identity for every internal operation.
3. Match the caller identity, target service, operation, and HTTP method.
4. Check ownership or delegated workflow context where a user-owned resource is involved.
5. Reject missing, expired, wrong-issuer, wrong-audience, or contradictory identity context.
6. Return a reason code suitable for telemetry without disclosing sensitive data to the caller.

Illustrative Rego-style rules:

```rego
package ecommerce.authz

default allow := false

allow if {
  input.subject.kind == "workload"
  input.subject.id == "order"
  input.action == "payment.authorize"
  input.resource.type == "payment"
  input.context.m_tls == true
  input.context.audience == "payment"
}

allow if {
  input.subject.kind == "user"
  input.action == "cart.read"
  input.resource.owner_id == input.subject.user_id
}
```

The examples illustrate the decision shape only. The implementation must add explicit validation, policy tests, and a clear separation between user and workload identities.

## 5. Enforcement placement

```text
Request
  |
  v
Ingress / service proxy ---- validates transport identity and coarse route policy
  |
  v
Service endpoint ---------- validates input and builds normalized policy request
  |
  v
OPA decision point -------- returns allow/deny + reason/version
  |
  v
Business operation -------- executes only after an allow decision
  |
  v
Telemetry ------------------ records decision, outcome, latency, and correlation ID
```

Mesh policy should answer: “May this authenticated workload reach this service and route?” OPA or equivalent application-level policy should answer: “May this subject perform this action on this resource in this context?”

## 6. Contract tests to implement later

- Each allowed row in the authorization matrix has at least one positive test.
- Each forbidden direct lateral call has a negative test.
- Ownership checks cover both matching and mismatching customer IDs.
- Expired, wrong-audience, and wrong-issuer user tokens are rejected.
- Policy dependency errors fail closed.
- Changing a policy version changes the decision only for the intended operation.
- Error responses do not reveal protected resource existence to unauthorized callers.

