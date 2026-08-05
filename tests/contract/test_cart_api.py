import pytest
from fastapi.testclient import TestClient

from services.cart.app import main


class FakeOrderClient:
    async def submit(self, cart: main.Cart) -> dict:
        return {
            "id": "order-test-0001",
            "customer_id": cart.customer_id,
            "status": "created",
        }


@pytest.fixture(autouse=True)
def reset_cart_state():
    main.CARTS.clear()
    previous_client = main.app.state.order_client
    main.app.state.order_client = FakeOrderClient()
    yield
    main.CARTS.clear()
    main.app.state.order_client = previous_client


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
    assert added.json()["items"] == [{"product_id": "p-001", "quantity": 2}]

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
        "status": "created",
    }

