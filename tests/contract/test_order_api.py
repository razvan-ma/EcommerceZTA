import pytest
from fastapi.testclient import TestClient

from services.order.app import main


@pytest.fixture(autouse=True)
def reset_order_state():
    main.ORDERS.clear()
    main._sequence = 0
    yield
    main.ORDERS.clear()


client = TestClient(main.app)


def order_payload() -> dict:
    return {
        "customer_id": "customer-1",
        "source_cart_id": "customer-1",
        "items": [{"product_id": "p-001", "quantity": 2}],
    }


def test_order_can_be_created_and_retrieved() -> None:
    created = client.post("/orders", json=order_payload())

    assert created.status_code == 201
    assert created.json()["id"] == "order-0001"
    assert created.json()["status"] == "created"

    fetched = client.get("/orders/order-0001")
    assert fetched.status_code == 200
    assert fetched.json()["customer_id"] == "customer-1"


def test_orders_can_be_filtered_by_customer() -> None:
    client.post("/orders", json=order_payload())
    other = order_payload()
    other["customer_id"] = "customer-2"
    client.post("/orders", json=other)

    response = client.get("/orders?customer_id=customer-1")

    assert response.status_code == 200
    assert [order["id"] for order in response.json()] == ["order-0001"]


def test_unknown_order_is_not_found() -> None:
    response = client.get("/orders/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"detail": "order not found"}


def test_order_can_enter_inventory_pending_state() -> None:
    client.post("/orders", json=order_payload())

    response = client.post("/orders/order-0001/reserve")

    assert response.status_code == 200
    assert response.json()["status"] == "inventory_pending"

