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


class FakeOpaClient:
    def __init__(self, allow: bool = True) -> None:
        self.allow = allow
        self.inputs: list[dict] = []

    async def decide(self, policy_input: dict) -> dict:
        self.inputs.append(policy_input)
        return {"allow": self.allow, "reason": "denied by test policy"}


client = TestClient(main.app)


def test_ui_is_served() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Zero-Trust E-commerce" in response.text
    assert "checkout()" in response.text


def test_ui_api_proxies_products_and_cart() -> None:
    previous_product_client = main.app.state.product_client
    previous_cart_client = main.app.state.cart_client
    previous_opa_client = main.app.state.opa_client
    main.app.state.product_client = FakeServiceClient()
    main.app.state.cart_client = FakeServiceClient()
    main.app.state.opa_client = FakeOpaClient()
    try:
        assert client.get("/api/products").json() == {"items": [], "count": 0}
        assert client.get("/api/cart/customer-1").json()["items"] == []
        assert client.post("/api/cart/customer-1/checkout").status_code == 201
    finally:
        main.app.state.product_client = previous_product_client
        main.app.state.cart_client = previous_cart_client
        main.app.state.opa_client = previous_opa_client


def test_ui_api_stops_before_calling_a_service_when_opa_denies() -> None:
    previous_product_client = main.app.state.product_client
    previous_opa_client = main.app.state.opa_client
    main.app.state.product_client = FakeServiceClient()
    main.app.state.opa_client = FakeOpaClient(allow=False)
    try:
        response = client.get("/api/products")

        assert response.status_code == 403
        assert response.json()["detail"] == "denied by test policy"
    finally:
        main.app.state.product_client = previous_product_client
        main.app.state.opa_client = previous_opa_client
