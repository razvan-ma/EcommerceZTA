# Observability and Evaluation Design

## 1. Evaluation questions

The implementation will answer two separate questions:

1. **Security:** Does the system block the unauthorized actions identified in the threat model while preserving the normal shopping flow?
2. **Cost:** What latency, throughput, and resource overhead is introduced by mTLS, authorization decisions, and telemetry compared with the same application baseline?

## 2. Variants

Both variants must use the same service code, deployment resources, test data, request mix, and measurement procedure.

### Baseline

- Internal network reachability is treated as sufficient for service calls.
- Strict mTLS and workload-aware policy are disabled or placed in permissive mode.
- The application still performs basic input validation and user checks required for the business flow.

### Zero-Trust variant

- Strict service-to-service mTLS.
- Default-deny mesh authorization.
- OPA/domain authorization for action, ownership, and workflow context.
- Structured security telemetry with correlation IDs.

The baseline is not intended to be “unsecured software”; it represents the perimeter-style internal trust model against which the Zero-Trust controls are evaluated.

## 3. Security event schema

Every protected request should produce a structured decision event, with secret and payment values redacted:

| Field | Meaning |
|---|---|
| `timestamp` | Event time in UTC |
| `request_id` | End-to-end correlation identifier |
| `trace_id` | Distributed trace correlation |
| `caller_identity` | Authenticated user or workload identity |
| `target_service` | Intended service |
| `operation` | Named operation from the contract document |
| `resource_type` | Resource category, never raw sensitive contents |
| `resource_id_hash` | Optional stable hash for correlation without disclosure |
| `decision` | `allow` or `deny` |
| `reason_code` | Stable explanation such as `invalid_audience` or `policy_denied` |
| `policy_version` | Version that produced the decision |
| `status_code` | Result returned to the caller |
| `duration_ms` | Decision or request duration |
| `environment` | Baseline or Zero-Trust variant |

Never log access tokens, private keys, raw payment credentials, or complete personal records.

## 4. Metrics

### Security metrics

- Allowed and denied requests by operation and caller identity.
- Denials by reason code.
- Invalid token and invalid workload-identity attempts.
- Direct lateral-call attempts by source and target service.
- Policy dependency failures and fail-closed decisions.
- Requests missing correlation or trace context.

### Performance metrics

- End-to-end request latency: p50, p95, and p99.
- Per-service latency and error rate.
- mTLS handshake or connection-establishment cost where observable.
- Policy decision latency and timeout count.
- Requests per second and completed transactions per second.
- CPU and memory per service/proxy.
- Telemetry export latency and dropped spans/events.

## 5. Trace points

The normal checkout trace should show:

```text
ingress
  -> cart.checkout
  -> order.create
  -> inventory.reserve
  -> payment.authorize
  -> notification.publish
```

Each internal span should include service identity, operation name, authorization decision, and policy version as non-sensitive attributes. The trace must make a denied branch visible without recording secrets.

## 6. Security test matrix

| Scenario | Baseline expectation | Zero-Trust expectation | Evidence |
|---|---|---|---|
| Normal checkout | Succeeds | Succeeds | Trace and business result |
| Product → Payment direct call | May reach an internal endpoint | Denied | Denial event and response |
| Cart → Inventory mutation | May reach an internal endpoint | Denied | Denial event and policy reason |
| Customer A reads Customer B order | Application-dependent; must be tested | Denied | Ownership policy decision |
| Expired/wrong-audience token | Denied at authentication | Denied at authentication | Token failure event |
| Invalid workload identity | May be reachable if network permits | Denied by mTLS/policy | Transport/policy evidence |
| Policy dependency unavailable | Behavior recorded | Fail closed | Failure and denial events |
| Secret leakage in logs | Must be checked | Must be absent | Automated redaction scan |

## 7. Experimental procedure

1. Pin the application version, test dataset, deployment configuration, and resource limits.
2. Warm up each variant without recording measurements.
3. Run the same normal-flow workload against the baseline and Zero-Trust variants.
4. Repeat each attack scenario enough times to distinguish deterministic policy behavior from transient errors.
5. Repeat performance runs with a fixed request rate and with a controlled concurrency sweep.
6. Capture raw results, environment metadata, configuration hashes, and logs.
7. Report central values and distributions, not only a single average.
8. Explain failed runs, resource saturation, and limitations instead of silently discarding them.

## 8. Evaluation outputs

The final thesis should include:

- A table of security scenarios and observed decisions.
- Latency and throughput plots for both variants.
- An overhead table for mTLS, policy evaluation, proxies, and telemetry where separately measurable.
- Representative traces for a successful checkout and a denied lateral call.
- A reproducibility appendix containing commands, configuration identifiers, and test-data generation details.

