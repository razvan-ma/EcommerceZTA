import pytest
from fastapi.testclient import TestClient

from services.order.app import main


class FakeInventoryClient:
    async def reserve(self, order: main.Order) -> dict:
        return {"id": "reservation-test-0001"}


class FakePaymentClient:
    async def authorize(self, order: main.Order) -> dict:
        return {"id": "payment-test-0001"}


class FakeNotificationClient:
    async def publish(self, order: main.Order) -> dict:
        return {"id": "notification-test-0001"}


@pytest.fixture(autouse=True)
def reset_order_state():
    main.ORDERS.clear()
    main._sequence = 0
    previous_client = main.app.state.inventory_client
    previous_payment_client = main.app.state.payment_client
    previous_notification_client = main.app.state.notification_client
    main.app.state.inventory_client = FakeInventoryClient()
    main.app.state.payment_client = FakePaymentClient()
    main.app.state.notification_client = FakeNotificationClient()
    yield
    main.ORDERS.clear()
    main.app.state.inventory_client = previous_client
    main.app.state.payment_client = previous_payment_client
    main.app.state.notification_client = previous_notification_client


client = TestClient(main.app)


def order_payload() -> dict:
    return {
        "customer_id": "customer-1",
        "source_cart_id": "customer-1",
        "items": [{"product_id": "p-001", "quantity": 2, "unit_price_cents": 4999}],
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


def test_order_can_reserve_inventory() -> None:
    client.post("/orders", json=order_payload())

    response = client.post("/orders/order-0001/reserve")

    assert response.status_code == 200
    assert response.json()["status"] == "inventory_reserved"
    assert response.json()["reservation_id"] == "reservation-test-0001"


def test_order_confirmation_authorizes_payment_and_notifies() -> None:
    client.post("/orders", json=order_payload())
    client.post("/orders/order-0001/reserve")

    response = client.post("/orders/order-0001/confirm")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "confirmed"
    assert body["total_cents"] == 9998
    assert body["payment_id"] == "payment-test-0001"
    assert body["notification_id"] == "notification-test-0001"
