package system.authz

# Authorizes calls to OPA's own REST API (enabled with --authorization=basic).
# Only policy decisions and health checks are allowed. Every management call
# (PUT/DELETE /v1/policies, PUT/PATCH /v1/data, /v1/config, ...) is denied, so
# a caller that reaches OPA cannot rewrite the policy it is judged by.

default allow := false

allow if {
    input.method == "POST"
    input.path == ["v1", "data", "ecommerce", "authz", "decision"]
}

allow if {
    input.method == "GET"
    input.path == ["health"]
}
