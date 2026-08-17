import os
import time
from contextlib import asynccontextmanager
from typing import Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field

try:
    import psycopg
    from psycopg.types.json import Json
except ImportError:  # Keep deterministic unit tests lightweight.
    psycopg = None
    Json = None


class OrderItem(BaseModel):
    product_id: str = Field(..., min_length=1)
    quantity: int = Field(..., ge=1, le=100)
    unit_price_cents: int = Field(..., ge=0)


class OrderCreate(BaseModel):
    customer_id: str = Field(..., min_length=1)
    items: List[OrderItem] = Field(..., min_length=1)
    source_cart_id: Optional[str] = None


class Order(BaseModel):
    id: str
    customer_id: str
    items: List[OrderItem]
    source_cart_id: Optional[str] = None
    total_cents: int = Field(..., ge=0)
    status: str
    reservation_id: Optional[str] = None
    payment_id: Optional[str] = None
    notification_id: Optional[str] = None


ORDERS: Dict[str, Order] = {}
_sequence = 0


class InMemoryOrderRepository:
    def initialize(self) -> None:
        return None

    def count(self) -> int:
        return len(ORDERS)

    def create(self, order: Order) -> Order:
        ORDERS[order.id] = order
        return order

    def save(self, order: Order) -> Order:
        ORDERS[order.id] = order
        return order

    def list(self, customer_id: Optional[str] = None) -> List[Order]:
        orders = list(ORDERS.values())
        if customer_id is not None:
            orders = [order for order in orders if order.customer_id == customer_id]
        return orders

    def get(self, order_id: str) -> Optional[Order]:
        return ORDERS.get(order_id)


class PostgresOrderRepository:
    def __init__(self, database_url: str) -> None:
        if psycopg is None or Json is None:
            raise RuntimeError("psycopg is required when DATABASE_URL is configured")
        self.database_url = database_url

    def initialize(self) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL,
                    source_cart_id TEXT,
                    items JSONB NOT NULL,
                    total_cents INTEGER NOT NULL CHECK (total_cents >= 0),
                    status TEXT NOT NULL,
                    reservation_id TEXT,
                    payment_id TEXT,
                    notification_id TEXT
                )
                """
            )

    def count(self) -> int:
        with psycopg.connect(self.database_url) as connection:
            return connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0]

    def next_id(self) -> str:
        with psycopg.connect(self.database_url) as connection:
            next_number = connection.execute(
                """
                SELECT COALESCE(MAX(CAST(SUBSTRING(id FROM 7) AS INTEGER)), 0) + 1
                FROM orders WHERE id LIKE 'order-%'
                """
            ).fetchone()[0]
        return f"order-{next_number:04d}"

    def _from_row(self, row: tuple) -> Order:
        return Order(
            id=row[0],
            customer_id=row[1],
            source_cart_id=row[2],
            items=[OrderItem(**item) for item in row[3]],
            total_cents=row[4],
            status=row[5],
            reservation_id=row[6],
            payment_id=row[7],
            notification_id=row[8],
        )

    def create(self, order: Order) -> Order:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                """
                INSERT INTO orders (
                    id, customer_id, source_cart_id, items, total_cents, status,
                    reservation_id, payment_id, notification_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    order.id,
                    order.customer_id,
                    order.source_cart_id,
                    Json([item.model_dump() for item in order.items]),
                    order.total_cents,
                    order.status,
                    order.reservation_id,
                    order.payment_id,
                    order.notification_id,
                ),
            )
        return order

    def save(self, order: Order) -> Order:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                """
                UPDATE orders SET status = %s, reservation_id = %s, payment_id = %s,
                    notification_id = %s WHERE id = %s
                """,
                (
                    order.status,
                    order.reservation_id,
                    order.payment_id,
                    order.notification_id,
                    order.id,
                ),
            )
        return order

    def list(self, customer_id: Optional[str] = None) -> List[Order]:
        query = (
            "SELECT id, customer_id, source_cart_id, items, total_cents, status, "
            "reservation_id, payment_id, notification_id FROM orders"
        )
        params = ()
        if customer_id is not None:
            query += " WHERE customer_id = %s"
            params = (customer_id,)
        query += " ORDER BY id"
        with psycopg.connect(self.database_url) as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._from_row(row) for row in rows]

    def get(self, order_id: str) -> Optional[Order]:
        with psycopg.connect(self.database_url) as connection:
            row = connection.execute(
                "SELECT id, customer_id, source_cart_id, items, total_cents, status, "
                "reservation_id, payment_id, notification_id FROM orders WHERE id = %s",
                (order_id,),
            ).fetchone()
        return None if row is None else self._from_row(row)


def _build_repository():
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return PostgresOrderRepository(database_url)
    return InMemoryOrderRepository()


@asynccontextmanager
async def lifespan(application: FastAPI):
    repository = application.state.order_repository
    for attempt in range(15):
        try:
            repository.initialize()
            break
        except Exception:
            if attempt == 14:
                raise
            time.sleep(2)
    yield


app = FastAPI(
    title="Zero-Trust E-commerce - Order Service",
    version="0.1.0",
    description="M1 order service with deterministic in-memory persistence.",
    lifespan=lifespan,
)
app.state.order_repository = _build_repository()


class InventoryClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def reserve(self, order: Order) -> dict:
        payload = {
            "order_id": order.id,
            "items": [item.model_dump() for item in order.items],
        }
        async with httpx.AsyncClient(base_url=self.base_url, timeout=5.0) as client:
            response = await client.post("/reservations", json=payload)
        response.raise_for_status()
        return response.json()


class PaymentClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def authorize(self, order: Order) -> dict:
        payload = {
            "order_id": order.id,
            "customer_id": order.customer_id,
            "amount_cents": order.total_cents,
            "currency": "EUR",
            "payment_method_token": "sandbox-token",
        }
        async with httpx.AsyncClient(base_url=self.base_url, timeout=5.0) as client:
            response = await client.post("/authorizations", json=payload)
        response.raise_for_status()
        return response.json()


class NotificationClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def publish(self, order: Order) -> dict:
        payload = {
            "order_id": order.id,
            "customer_id": order.customer_id,
            "event_type": "order.confirmed",
            "status": "confirmed",
        }
        async with httpx.AsyncClient(base_url=self.base_url, timeout=5.0) as client:
            response = await client.post("/events/order", json=payload)
        response.raise_for_status()
        return response.json()


app.state.inventory_client = InventoryClient(
    os.getenv("INVENTORY_SERVICE_URL", "http://inventory:8000")
)
app.state.payment_client = PaymentClient(os.getenv("PAYMENT_SERVICE_URL", "http://payment:8000"))
app.state.notification_client = NotificationClient(
    os.getenv("NOTIFICATION_SERVICE_URL", "http://notification:8000")
)


@app.get("/", tags=["meta"])
def root() -> dict:
    return {"service": "order", "version": app.version}


@app.get("/health/live", tags=["health"])
def liveness() -> dict:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def readiness() -> dict:
    return {"status": "ready", "order_count": app.state.order_repository.count()}


@app.post("/orders", response_model=Order, status_code=status.HTTP_201_CREATED, tags=["orders"])
def create_order(order_input: OrderCreate) -> Order:
    global _sequence
    repository = app.state.order_repository
    if hasattr(repository, "next_id"):
        order_id = repository.next_id()
    else:
        _sequence += 1
        order_id = f"order-{_sequence:04d}"
    order = Order(
        id=order_id,
        customer_id=order_input.customer_id,
        items=order_input.items,
        source_cart_id=order_input.source_cart_id,
        total_cents=sum(item.quantity * item.unit_price_cents for item in order_input.items),
        status="created",
    )
    return app.state.order_repository.create(order)


@app.get("/orders", response_model=List[Order], tags=["orders"])
def list_orders(
    customer_id: Optional[str] = Query(default=None, min_length=1),
) -> List[Order]:
    return app.state.order_repository.list(customer_id)


@app.get("/orders/{order_id}", response_model=Order, tags=["orders"])
def get_order(order_id: str) -> Order:
    order = app.state.order_repository.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    return order


@app.post("/orders/{order_id}/reserve", response_model=Order, tags=["orders"])
async def reserve_order(order_id: str) -> Order:
    order = app.state.order_repository.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")

    try:
        reservation = await app.state.inventory_client.reserve(order)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 409:
            raise HTTPException(status_code=409, detail="insufficient inventory") from exc
        raise HTTPException(status_code=502, detail="inventory service unavailable") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="inventory service unavailable") from exc

    order.status = "inventory_reserved"
    order.reservation_id = reservation["id"]
    return app.state.order_repository.save(order)


@app.post("/orders/{order_id}/confirm", response_model=Order, tags=["orders"])
async def confirm_order(order_id: str) -> Order:
    order = app.state.order_repository.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    if order.status == "confirmed":
        return order
    if order.status != "inventory_reserved":
        raise HTTPException(status_code=409, detail="inventory must be reserved before confirmation")

    try:
        payment = await app.state.payment_client.authorize(order)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="payment service unavailable") from exc

    order.payment_id = payment["id"]
    order.status = "payment_authorized"
    try:
        notification = await app.state.notification_client.publish(order)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="notification service unavailable") from exc

    order.notification_id = notification["id"]
    order.status = "confirmed"
    return app.state.order_repository.save(order)
