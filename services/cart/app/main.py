import os
from typing import Dict, List

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel, Field


class CartItem(BaseModel):
    product_id: str = Field(..., min_length=1)
    quantity: int = Field(..., ge=1, le=100)


class CartItemUpdate(CartItem):
    pass


class Cart(BaseModel):
    customer_id: str = Field(..., min_length=1)
    items: List[CartItem] = Field(default_factory=list)


class CheckoutResponse(BaseModel):
    order_id: str
    customer_id: str
    status: str


CARTS: Dict[str, Cart] = {}


class OrderClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def submit(self, cart: Cart) -> dict:
        payload = {
            "customer_id": cart.customer_id,
            "items": [item.model_dump() for item in cart.items],
            "source_cart_id": cart.customer_id,
        }
        async with httpx.AsyncClient(base_url=self.base_url, timeout=5.0) as client:
            response = await client.post("/orders", json=payload)
        response.raise_for_status()
        return response.json()


app = FastAPI(
    title="Zero-Trust E-commerce - Cart Service",
    version="0.1.0",
    description="M1 customer cart service with an internal Order checkout call.",
)
app.state.order_client = OrderClient(os.getenv("ORDER_SERVICE_URL", "http://order:8000"))


@app.get("/", tags=["meta"])
def root() -> dict:
    return {"service": "cart", "version": app.version}


@app.get("/health/live", tags=["health"])
def liveness() -> dict:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def readiness() -> dict:
    return {"status": "ready", "cart_count": len(CARTS)}


def _get_or_create_cart(customer_id: str) -> Cart:
    return CARTS.setdefault(customer_id, Cart(customer_id=customer_id))


@app.get("/carts/{customer_id}", response_model=Cart, tags=["carts"])
def get_cart(customer_id: str) -> Cart:
    return _get_or_create_cart(customer_id)


@app.put("/carts/{customer_id}/items", response_model=Cart, tags=["carts"])
def put_cart_item(customer_id: str, item: CartItemUpdate) -> Cart:
    cart = _get_or_create_cart(customer_id)
    for index, existing in enumerate(cart.items):
        if existing.product_id == item.product_id:
            cart.items[index] = item
            return cart
    cart.items.append(item)
    return cart


@app.delete("/carts/{customer_id}/items/{product_id}", response_model=Cart, tags=["carts"])
def delete_cart_item(customer_id: str, product_id: str) -> Cart:
    cart = _get_or_create_cart(customer_id)
    cart.items = [item for item in cart.items if item.product_id != product_id]
    return cart


@app.post(
    "/carts/{customer_id}/checkout",
    response_model=CheckoutResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["carts"],
)
async def checkout(customer_id: str, request: Request) -> CheckoutResponse:
    cart = _get_or_create_cart(customer_id)
    if not cart.items:
        raise HTTPException(status_code=400, detail="cart is empty")

    try:
        order = await request.app.state.order_client.submit(cart)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="order service unavailable") from exc

    return CheckoutResponse(
        order_id=order["id"],
        customer_id=order["customer_id"],
        status=order["status"],
    )

