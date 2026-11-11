import httpx
import pytest
from fastapi.testclient import TestClient

from services.order.app import main


def _http_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://test")
    return httpx.HTTPStatusError(
        "error", request=request, response=httpx.Response(status_code, request=request)
    )


class FakeInventoryClient:
    def __init__(self) -> None:
        self.reserve_calls = 0
        self.released: list[str] = []
        self.reserve_error: Exception | None = None
        self.release_error: Exception | None = None

    async def reserve(self, order: main.Order) -> dict:
        self.reserve_calls += 1
        if self.reserve_error:
            raise self.reserve_error
        return {"id": "reservation-test-0001"}

    async def release(self, reservation_id: str) -> dict:
        if self.release_error:
            raise self.release_error
        self.released.append(reservation_id)
        return {"id": reservation_id, "status": "released"}


class FakePaymentClient:
    def __init__(self) -> None:
        self.calls = 0
        self.error: Exception | None = None

    async def authorize(self, order: main.Order) -> dict:
        self.calls += 1
        if self.error:
            raise self.error
        return {"id": "payment-test-0001"}


class FakeNotificationClient:
    def __init__(self) -> None:
        self.error: Exception | None = None

    async def publish(self, order: main.Order) -> dict:
        if self.error:
            raise self.error
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


def _fakes() -> tuple[FakeInventoryClient, FakePaymentClient, FakeNotificationClient]:
    return (
        main.app.state.inventory_client,
        main.app.state.payment_client,
        main.app.state.notification_client,
    )


def test_order_refused_by_inventory_is_marked_rejected() -> None:
    inventory, _, _ = _fakes()
    inventory.reserve_error = _http_error(409)
    client.post("/orders", json=order_payload())

    response = client.post("/orders/order-0001/reserve")

    assert response.status_code == 409
    assert response.json() == {"detail": "insufficient inventory"}
    assert client.get("/orders/order-0001").json()["status"] == "rejected"
    # A rejected order is final.
    assert client.post("/orders/order-0001/reserve").status_code == 409
    assert client.post("/orders/order-0001/confirm").status_code == 409


def test_reserving_twice_holds_stock_once() -> None:
    inventory, _, _ = _fakes()
    client.post("/orders", json=order_payload())

    client.post("/orders/order-0001/reserve")
    second = client.post("/orders/order-0001/reserve")

    assert second.status_code == 200
    assert second.json()["status"] == "inventory_reserved"
    assert inventory.reserve_calls == 1


def test_failed_payment_releases_the_reservation() -> None:
    inventory, payment, _ = _fakes()
    payment.error = httpx.ConnectError("payment down")
    client.post("/orders", json=order_payload())
    client.post("/orders/order-0001/reserve")

    response = client.post("/orders/order-0001/confirm")

    assert response.status_code == 502
    assert inventory.released == ["reservation-test-0001"]
    order = client.get("/orders/order-0001").json()
    assert order["status"] == "cancelled"
    assert order["payment_id"] is None


def test_failed_release_is_recorded_on_the_order() -> None:
    inventory, payment, _ = _fakes()
    payment.error = httpx.ConnectError("payment down")
    inventory.release_error = httpx.ConnectError("inventory down")
    client.post("/orders", json=order_payload())
    client.post("/orders/order-0001/reserve")

    response = client.post("/orders/order-0001/confirm")

    assert response.status_code == 502
    assert client.get("/orders/order-0001").json()["status"] == "release_failed"


def test_notification_retry_does_not_authorize_payment_twice() -> None:
    _, payment, notification = _fakes()
    notification.error = httpx.ConnectError("notification down")
    client.post("/orders", json=order_payload())
    client.post("/orders/order-0001/reserve")

    failed = client.post("/orders/order-0001/confirm")
    assert failed.status_code == 502
    assert client.get("/orders/order-0001").json()["status"] == "payment_authorized"

    notification.error = None
    retried = client.post("/orders/order-0001/confirm")

    assert retried.status_code == 200
    assert retried.json()["status"] == "confirmed"
    assert retried.json()["payment_id"] == "payment-test-0001"
    assert payment.calls == 1
