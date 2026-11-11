import httpx
import pytest
from fastapi.testclient import TestClient

from services.cart.app import main


class FakeOrderClient:
    def __init__(self) -> None:
        self.reserve_status: int | None = None

    async def submit(self, cart: main.Cart) -> dict:
        return {
            "id": "order-test-0001",
            "customer_id": cart.customer_id,
            "status": "created",
        }

    async def reserve(self, order_id: str) -> dict:
        if self.reserve_status:
            request = httpx.Request("POST", "http://order/reserve")
            raise httpx.HTTPStatusError(
                "refused",
                request=request,
                response=httpx.Response(self.reserve_status, request=request),
            )
        return {
            "id": order_id,
            "customer_id": "customer-1",
            "status": "inventory_reserved",
        }

    async def confirm(self, order_id: str) -> dict:
        return {
            "id": order_id,
            "customer_id": "customer-1",
            "status": "confirmed",
        }


class FakeProductClient:
    async def get_product(self, product_id: str) -> dict:
        return {"id": product_id, "price_cents": 4999}


@pytest.fixture(autouse=True)
def reset_cart_state():
    main.CARTS.clear()
    previous_client = main.app.state.order_client
    previous_product_client = main.app.state.product_client
    main.app.state.order_client = FakeOrderClient()
    main.app.state.product_client = FakeProductClient()
    yield
    main.CARTS.clear()
    main.app.state.order_client = previous_client
    main.app.state.product_client = previous_product_client


client = TestClient(main.app)


def test_cart_starts_empty() -> None:
    response = client.get("/carts/customer-1")

    assert response.status_code == 200
    assert response.json() == {"customer_id": "customer-1", "items": []}


def test_cart_can_add_and_remove_item() -> None:
    added = client.put(
        "/carts/customer-1/items",
        json={"product_id": "p-001", "quantity": 2},
    )
    assert added.status_code == 200
    assert added.json()["items"] == [
        {"product_id": "p-001", "quantity": 2, "unit_price_cents": 4999}
    ]

    removed = client.delete("/carts/customer-1/items/p-001")
    assert removed.status_code == 200
    assert removed.json()["items"] == []


def test_empty_cart_cannot_checkout() -> None:
    response = client.post("/carts/customer-1/checkout")

    assert response.status_code == 400
    assert response.json() == {"detail": "cart is empty"}


def test_checkout_submits_cart_to_order_service() -> None:
    client.put(
        "/carts/customer-1/items",
        json={"product_id": "p-001", "quantity": 1},
    )

    response = client.post("/carts/customer-1/checkout")

    assert response.status_code == 201
    assert response.json() == {
        "order_id": "order-test-0001",
        "customer_id": "customer-1",
        "status": "confirmed",
    }


def test_successful_checkout_empties_the_cart() -> None:
    client.put("/carts/customer-1/items", json={"product_id": "p-001", "quantity": 1})

    assert client.post("/carts/customer-1/checkout").status_code == 201

    assert client.get("/carts/customer-1").json()["items"] == []
    # The same items cannot be bought twice.
    assert client.post("/carts/customer-1/checkout").status_code == 400


def test_refused_checkout_keeps_the_cart() -> None:
    main.app.state.order_client.reserve_status = 409
    client.put("/carts/customer-1/items", json={"product_id": "p-001", "quantity": 1})

    response = client.post("/carts/customer-1/checkout")

    assert response.status_code == 409
    assert response.json() == {"detail": "insufficient inventory"}
    assert [item["product_id"] for item in client.get("/carts/customer-1").json()["items"]] == [
        "p-001"
    ]
