package ecommerce.authz

default allow := false

roles := object.get(input.subject, "roles", [])
username := object.get(input.subject, "username", "")
action := object.get(input, "action", "")
resource := object.get(input, "resource", {})

allow if {
    "admin" in roles
}

allow if {
    action == "catalog:read"
    "customer" in roles
}

allow if {
    action == "catalog:read"
    "support" in roles
}

allow if {
    action == "cart:access"
    "customer" in roles
    username == object.get(resource, "customer_id", "")
}

allow if {
    action == "cart:access"
    "support" in roles
}

reason := "request permitted by policy" if { allow }

reason := "no policy rule permits this request" if { not allow }

decision := {"allow": allow, "reason": reason}
