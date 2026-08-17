from fastapi.testclient import TestClient

from services.frontend.app import main


class FakeServiceClient:
    async def request(self, method: str, path: str, **kwargs: object) -> dict:
        if path == "/products":
            return {"items": [], "count": 0}
        if path.startswith("/carts/") and method == "GET":
            return {"customer_id": "customer-1", "items": []}
        if path.endswith("/checkout"):
            return {"order_id": "order-test-0001", "customer_id": "customer-1", "status": "confirmed"}
        return {"customer_id": "customer-1", "items": []}


client = TestClient(main.app)


def test_ui_is_served() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Zero-Trust E-commerce" in response.text
    assert "checkout()" in response.text


def test_ui_api_proxies_products_and_cart() -> None:
    previous_product_client = main.app.state.product_client
    previous_cart_client = main.app.state.cart_client
    main.app.state.product_client = FakeServiceClient()
    main.app.state.cart_client = FakeServiceClient()
    try:
        assert client.get("/api/products").json() == {"items": [], "count": 0}
        assert client.get("/api/cart/customer-1").json()["items"] == []
        assert client.post("/api/cart/customer-1/checkout").status_code == 201
    finally:
        main.app.state.product_client = previous_product_client
        main.app.state.cart_client = previous_cart_client
