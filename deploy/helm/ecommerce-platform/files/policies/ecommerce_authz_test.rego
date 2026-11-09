package ecommerce.authz

test_customer_can_access_own_cart if {
    result := decision with input as {
        "subject": {"username": "customer-1", "roles": ["customer"]},
        "action": "cart:access",
        "resource": {"type": "cart", "customer_id": "customer-1"},
    }
    result.allow
}

test_customer_cannot_access_another_cart if {
    result := decision with input as {
        "subject": {"username": "customer-1", "roles": ["customer"]},
        "action": "cart:access",
        "resource": {"type": "cart", "customer_id": "customer-2"},
    }
    not result.allow
}

test_customer_can_read_catalog if {
    result := decision with input as {
        "subject": {"username": "customer-1", "roles": ["customer"]},
        "action": "catalog:read",
        "resource": {"type": "catalog"},
    }
    result.allow
}
