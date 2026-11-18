# Security evaluation: baseline vs Zero-Trust

- **baseline**: `baseline-20261111T125152Z.json`, namespace `ecommerce-baseline`, 10 attempts per attack, commit `7d3c79f-dirty`, sidecars: False
- **zero-trust**: `zero-trust-20261111T125152Z.json`, namespace `default`, 10 attempts per attack, commit `7d3c79f-dirty`, sidecars: True

Outcome = what happened to the attack (`blocked` / `allowed`), attempts with that outcome / attempts, and the layer that stopped it.

| ID | Threat | Scenario | Baseline | Zero-Trust |
|---|---|---|---|---|
| C-01 | - | Customer browses the catalog | allowed 10/10 | allowed 10/10 |
| C-02 | - | Customer reads their own cart | allowed 10/10 | allowed 10/10 |
| C-03 | - | Cart service looks up a product price (allowed edge) | allowed 10/10 | allowed 10/10 |
| C-04 | - | Customer checks out their own cart (once per run) | allowed 1/1 | allowed 1/1 |
| TM-01a | TM-01 | Compromised product creates a payment authorization | allowed 10/10 | blocked 10/10 (mesh) |
| TM-01b | TM-01 | Compromised product lists all payment authorizations | allowed 10/10 | blocked 10/10 (mesh) |
| TM-01c | TM-01 | Compromised product reads payment table with its DB login | allowed 10/10 | blocked 10/10 (database) |
| TM-02a | TM-02 | Compromised cart reserves stock without an order | allowed 10/10 | blocked 10/10 (mesh) |
| TM-02b | TM-02 | Compromised product rewrites stock levels in the database | allowed 10/10 | blocked 10/10 (database) |
| TM-03a | TM-03 | Customer reads another customer's cart | allowed 10/10 | blocked 10/10 (application) |
| TM-03b | TM-03 | Customer adds an item to another customer's cart | allowed 10/10 | blocked 10/10 (application) |
| TM-04a | TM-04 | Request without a token | blocked 10/10 (application) | blocked 10/10 (application) |
| TM-04b | TM-04 | Malformed token | blocked 10/10 (application) | blocked 10/10 (application) |
| TM-04c | TM-04 | Real token with the username changed to the victim | blocked 10/10 (application) | blocked 10/10 (application) |
| TM-04d | TM-04 | Unsigned token (alg=none) | blocked 10/10 (application) | blocked 10/10 (application) |
| TM-04e | TM-04 | Token signed with an attacker-chosen HS256 key | blocked 10/10 (application) | blocked 10/10 (application) |
| TM-04f | TM-04 | Valid Keycloak token issued to another client (admin-cli) | blocked 10/10 (application) | blocked 10/10 (application) |
| TM-05a | TM-05 | Pod without mesh identity reads a customer cart | allowed 10/10 | blocked 10/10 (transport) |
| TM-05b | TM-05 | Pod without mesh identity lists payment authorizations | allowed 10/10 | blocked 10/10 (transport) |
| TM-05c | TM-05 | Pod with an untrusted mesh identity reads a customer cart | allowed 10/10 | blocked 10/10 (mesh) |
| TM-06a | TM-06 | Compromised cart lists a customer's orders (may only create) | allowed 10/10 | blocked 10/10 (mesh) |
| TM-06b | TM-06 | Compromised order lists payments (may only authorize) | allowed 10/10 | blocked 10/10 (mesh) |
| TM-06c | TM-06 | Compromised product opens the Keycloak admin console | allowed 10/10 | blocked 10/10 (mesh) |
| TM-06d | TM-06 | Compromised product uploads a policy to OPA | n/a | blocked 10/10 (mesh) |
| TM-07 | TM-07 | Protected request while the policy engine is down | n/a | blocked 10/10 (fail-closed) |
| TM-04g | TM-04 | Replay of an expired token | blocked 10/10 (application) | blocked 10/10 (application) |
| TM-09 | TM-09 | Credentials or tokens in container logs | blocked (logging) | blocked (logging) |

## Blocking rate (attacks run in both variants)

| Variant | Scenarios blocked | Attempts blocked | Attack success rate |
|---|---|---|---|
| baseline | 8/21 | 71/201 | 65% |
| zero-trust | 21/21 | 201/201 | 0% |

Fisher's exact test, blocked vs not blocked by variant (two-sided):
- per scenario (primary): p = 1.59e-05
- per attempt (secondary; attempts within a scenario are not independent): p = 1.77e-53

Legitimate flow (C-*) succeeded in both variants: yes.
Scenarios marked n/a have no counterpart in the baseline (it has no policy engine) and are left out of the test.
