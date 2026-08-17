import pytest
from fastapi.testclient import TestClient

from services.inventory.app import main


@pytest.fixture(autouse=True)
def reset_inventory_state():
    main.STOCK.clear()
    main.STOCK.update({key: value.model_copy() for key, value in main.INITIAL_STOCK.items()})
    main.RESERVATIONS.clear()
    main._sequence = 0
    yield
    main.STOCK.clear()
    main.RESERVATIONS.clear()


client = TestClient(main.app)


def reservation_payload() -> dict:
    return {"order_id": "order-0001", "items": [{"product_id": "p-001", "quantity": 2}]}


def test_inventory_lists_deterministic_stock() -> None:
    response = client.get("/inventory")

    assert response.status_code == 200
    assert [(item["product_id"], item["available"]) for item in response.json()] == [
        ("p-001", 10),
        ("p-002", 25),
        ("p-003", 5),
    ]


def test_reservation_decreases_available_stock() -> None:
    response = client.post("/reservations", json=reservation_payload())

    assert response.status_code == 201
    assert response.json()["id"] == "reservation-0001"
    assert client.get("/inventory/p-001").json() == {
        "product_id": "p-001",
        "available": 8,
        "reserved": 2,
    }


def test_reservation_rejects_insufficient_stock() -> None:
    response = client.post(
        "/reservations",
        json={"order_id": "order-0001", "items": [{"product_id": "p-001", "quantity": 11}]},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "insufficient stock: p-001"}


def test_release_returns_stock_to_available() -> None:
    created = client.post("/reservations", json=reservation_payload()).json()

    response = client.delete(f"/reservations/{created['id']}")

    assert response.status_code == 200
    assert response.json()["status"] == "released"
    assert client.get("/inventory/p-001").json()["available"] == 10


def test_unknown_product_stock_is_not_found() -> None:
    response = client.get("/inventory/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"detail": "product stock not found"}

