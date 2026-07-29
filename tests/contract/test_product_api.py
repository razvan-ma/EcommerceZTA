from fastapi.testclient import TestClient

from services.product.app.main import app


client = TestClient(app)


def test_root_identifies_product_service() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"service": "product", "version": "0.1.0"}


def test_health_endpoints_are_available() -> None:
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ready", "catalog_size": 3}


def test_catalog_returns_deterministic_products() -> None:
    response = client.get("/products?limit=2")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert [item["id"] for item in body["items"]] == ["p-001", "p-002"]


def test_product_lookup_returns_product() -> None:
    response = client.get("/products/p-002")

    assert response.status_code == 200
    assert response.json()["name"] == "Encrypted Notebook"


def test_missing_product_is_not_found() -> None:
    response = client.get("/products/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"detail": "product not found"}

