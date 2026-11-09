package system.authz

test_decision_endpoint_allowed if {
    allow with input as {"method": "POST", "path": ["v1", "data", "ecommerce", "authz", "decision"]}
}

test_health_allowed if {
    allow with input as {"method": "GET", "path": ["health"]}
}

test_policy_upload_denied if {
    not allow with input as {"method": "PUT", "path": ["v1", "policies", "ecommerce_authz.rego"]}
}

test_policy_delete_denied if {
    not allow with input as {"method": "DELETE", "path": ["v1", "policies", "ecommerce_authz.rego"]}
}

test_policy_listing_denied if {
    not allow with input as {"method": "GET", "path": ["v1", "policies"]}
}

test_data_write_denied if {
    not allow with input as {"method": "PUT", "path": ["v1", "data", "ecommerce", "authz"]}
}

test_other_data_read_denied if {
    not allow with input as {"method": "POST", "path": ["v1", "data", "ecommerce", "authz", "allow"]}
}

test_config_read_denied if {
    not allow with input as {"method": "GET", "path": ["v1", "config"]}
}
