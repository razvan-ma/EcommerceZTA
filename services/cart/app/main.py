import os
import time
from contextlib import asynccontextmanager
from typing import Dict, List

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel, Field

try:
    import psycopg
except ImportError:  # Keep deterministic unit tests lightweight.
    psycopg = None


class CartItem(BaseModel):
    product_id: str = Field(..., min_length=1)
    quantity: int = Field(..., ge=1, le=100)
    unit_price_cents: int = Field(..., ge=0)


class CartItemUpdate(BaseModel):
    product_id: str = Field(..., min_length=1)
    quantity: int = Field(..., ge=1, le=100)


class Cart(BaseModel):
    customer_id: str = Field(..., min_length=1)
    items: List[CartItem] = Field(default_factory=list)


class CheckoutResponse(BaseModel):
    order_id: str
    customer_id: str
    status: str


CARTS: Dict[str, Cart] = {}


class InMemoryCartRepository:
    def initialize(self) -> None:
        return None

    def count(self) -> int:
        return len(CARTS)

    def get(self, customer_id: str) -> Cart:
        return CARTS.setdefault(customer_id, Cart(customer_id=customer_id))

    def put_item(self, customer_id: str, item: CartItem) -> Cart:
        cart = self.get(customer_id)
        for index, existing in enumerate(cart.items):
            if existing.product_id == item.product_id:
                cart.items[index] = item
                return cart
        cart.items.append(item)
        return cart

    def delete_item(self, customer_id: str, product_id: str) -> Cart:
        cart = self.get(customer_id)
        cart.items = [item for item in cart.items if item.product_id != product_id]
        return cart


class PostgresCartRepository:
    def __init__(self, database_url: str) -> None:
        if psycopg is None:
            raise RuntimeError("psycopg is required when DATABASE_URL is configured")
        self.database_url = database_url

    def initialize(self) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS carts (
                    customer_id TEXT PRIMARY KEY
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cart_items (
                    customer_id TEXT NOT NULL REFERENCES carts(customer_id) ON DELETE CASCADE,
                    product_id TEXT NOT NULL,
                    quantity INTEGER NOT NULL CHECK (quantity > 0),
                    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0),
                    PRIMARY KEY (customer_id, product_id)
                )
                """
            )

    def count(self) -> int:
        with psycopg.connect(self.database_url) as connection:
            return connection.execute("SELECT COUNT(*) FROM carts").fetchone()[0]

    def get(self, customer_id: str) -> Cart:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "INSERT INTO carts (customer_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (customer_id,),
            )
            rows = connection.execute(
                """
                SELECT product_id, quantity, unit_price_cents
                FROM cart_items WHERE customer_id = %s ORDER BY product_id
                """,
                (customer_id,),
            ).fetchall()
        return Cart(
            customer_id=customer_id,
            items=[CartItem(product_id=row[0], quantity=row[1], unit_price_cents=row[2]) for row in rows],
        )

    def put_item(self, customer_id: str, item: CartItem) -> Cart:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "INSERT INTO carts (customer_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (customer_id,),
            )
            connection.execute(
                """
                INSERT INTO cart_items (customer_id, product_id, quantity, unit_price_cents)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (customer_id, product_id) DO UPDATE SET
                    quantity = EXCLUDED.quantity,
                    unit_price_cents = EXCLUDED.unit_price_cents
                """,
                (customer_id, item.product_id, item.quantity, item.unit_price_cents),
            )
        return self.get(customer_id)

    def delete_item(self, customer_id: str, product_id: str) -> Cart:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "DELETE FROM cart_items WHERE customer_id = %s AND product_id = %s",
                (customer_id, product_id),
            )
        return self.get(customer_id)


def _build_repository():
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return PostgresCartRepository(database_url)
    return InMemoryCartRepository()


@asynccontextmanager
async def lifespan(application: FastAPI):
    repository = application.state.cart_repository
    for attempt in range(15):
        try:
            repository.initialize()
            break
        except Exception:
            if attempt == 14:
                raise
            time.sleep(2)
    yield


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

    async def reserve(self, order_id: str) -> dict:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=5.0) as client:
            response = await client.post(f"/orders/{order_id}/reserve")
        response.raise_for_status()
        return response.json()

    async def confirm(self, order_id: str) -> dict:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=5.0) as client:
            response = await client.post(f"/orders/{order_id}/confirm")
        response.raise_for_status()
        return response.json()


class ProductClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def get_product(self, product_id: str) -> dict:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=5.0) as client:
            response = await client.get(f"/products/{product_id}")
        response.raise_for_status()
        return response.json()

app = FastAPI(
    title="Zero-Trust E-commerce - Cart Service",
    version="0.1.0",
    description="M1 customer cart service with an internal Order checkout call.",
    lifespan=lifespan,
)
app.state.cart_repository = _build_repository()
app.state.order_client = OrderClient(os.getenv("ORDER_SERVICE_URL", "http://order:8000"))
app.state.product_client = ProductClient(os.getenv("PRODUCT_SERVICE_URL", "http://product:8000"))


@app.get("/", tags=["meta"])
def root() -> dict:
    return {"service": "cart", "version": app.version}


@app.get("/health/live", tags=["health"])
def liveness() -> dict:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def readiness() -> dict:
    return {"status": "ready", "cart_count": app.state.cart_repository.count()}


def _get_or_create_cart(customer_id: str) -> Cart:
    return app.state.cart_repository.get(customer_id)


@app.get("/carts/{customer_id}", response_model=Cart, tags=["carts"])
def get_cart(customer_id: str) -> Cart:
    return _get_or_create_cart(customer_id)


@app.put("/carts/{customer_id}/items", response_model=Cart, tags=["carts"])
async def put_cart_item(customer_id: str, item: CartItemUpdate, request: Request) -> Cart:
    try:
        product = await request.app.state.product_client.get_product(item.product_id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="product not found") from exc
        raise HTTPException(status_code=502, detail="product service unavailable") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="product service unavailable") from exc

    cart_item = CartItem(
        product_id=item.product_id,
        quantity=item.quantity,
        unit_price_cents=product["price_cents"],
    )
    return request.app.state.cart_repository.put_item(customer_id, cart_item)


@app.delete("/carts/{customer_id}/items/{product_id}", response_model=Cart, tags=["carts"])
def delete_cart_item(customer_id: str, product_id: str) -> Cart:
    return app.state.cart_repository.delete_item(customer_id, product_id)


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
        order = await request.app.state.order_client.reserve(order["id"])
        order = await request.app.state.order_client.confirm(order["id"])
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 409:
            raise HTTPException(status_code=409, detail="insufficient inventory") from exc
        raise HTTPException(status_code=502, detail="order service unavailable") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="order service unavailable") from exc

    return CheckoutResponse(
        order_id=order["id"],
        customer_id=order["customer_id"],
        status=order["status"],
    )
