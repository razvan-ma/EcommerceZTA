import pytest
from fastapi.testclient import TestClient

from services.notification.app import main


@pytest.fixture(autouse=True)
def reset_notification_state():
    main.NOTIFICATIONS.clear()
    main._sequence = 0
    yield
    main.NOTIFICATIONS.clear()


client = TestClient(main.app)


def test_order_event_is_queued() -> None:
    response = client.post(
        "/events/order",
        json={
            "order_id": "order-0001",
            "customer_id": "customer-1",
            "event_type": "order.confirmed",
            "status": "confirmed",
        },
    )

    assert response.status_code == 201
    assert response.json()["id"] == "notification-0001"
    assert response.json()["delivery_status"] == "queued"


def test_notifications_can_be_filtered_by_customer() -> None:
    payload = {
        "order_id": "order-0001",
        "customer_id": "customer-1",
        "event_type": "order.confirmed",
        "status": "confirmed",
    }
    client.post("/events/order", json=payload)
    payload["customer_id"] = "customer-2"
    client.post("/events/order", json=payload)

    response = client.get("/notifications?customer_id=customer-1")

    assert response.status_code == 200
    assert [item["customer_id"] for item in response.json()] == ["customer-1"]


def test_unknown_notification_is_not_found() -> None:
    response = client.get("/notifications/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"detail": "notification not found"}

