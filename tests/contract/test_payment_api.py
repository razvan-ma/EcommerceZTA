import pytest
from fastapi.testclient import TestClient

from services.payment.app import main


@pytest.fixture(autouse=True)
def reset_payment_state():
    main.AUTHORIZATIONS.clear()
    main._sequence = 0
    yield
    main.AUTHORIZATIONS.clear()


client = TestClient(main.app)


def payment_payload() -> dict:
    return {
        "order_id": "order-0001",
        "customer_id": "customer-1",
        "amount_cents": 9998,
        "currency": "EUR",
        "payment_method_token": "sandbox-token",
    }


def test_payment_authorization_is_created() -> None:
    response = client.post("/authorizations", json=payment_payload())

    assert response.status_code == 201
    assert response.json()["id"] == "payment-0001"
    assert response.json()["status"] == "authorized"
    assert response.json()["amount_cents"] == 9998


def test_payment_authorization_is_idempotent_per_order() -> None:
    first = client.post("/authorizations", json=payment_payload())
    second = client.post("/authorizations", json=payment_payload())

    assert first.json() == second.json()
    assert len(client.get("/authorizations").json()) == 1


def test_unknown_payment_authorization_is_not_found() -> None:
    response = client.get("/authorizations/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"detail": "payment authorization not found"}

