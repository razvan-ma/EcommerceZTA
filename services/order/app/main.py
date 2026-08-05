from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field


class OrderItem(BaseModel):
    product_id: str = Field(..., min_length=1)
    quantity: int = Field(..., ge=1, le=100)


class OrderCreate(BaseModel):
    customer_id: str = Field(..., min_length=1)
    items: List[OrderItem] = Field(..., min_length=1)
    source_cart_id: Optional[str] = None


class Order(BaseModel):
    id: str
    customer_id: str
    items: List[OrderItem]
    source_cart_id: Optional[str] = None
    status: str


ORDERS: Dict[str, Order] = {}
_sequence = 0


app = FastAPI(
    title="Zero-Trust E-commerce - Order Service",
    version="0.1.0",
    description="M1 order service with deterministic in-memory persistence.",
)


@app.get("/", tags=["meta"])
def root() -> dict:
    return {"service": "order", "version": app.version}


@app.get("/health/live", tags=["health"])
def liveness() -> dict:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def readiness() -> dict:
    return {"status": "ready", "order_count": len(ORDERS)}


@app.post("/orders", response_model=Order, status_code=status.HTTP_201_CREATED, tags=["orders"])
def create_order(order_input: OrderCreate) -> Order:
    global _sequence
    _sequence += 1
    order = Order(
        id=f"order-{_sequence:04d}",
        customer_id=order_input.customer_id,
        items=order_input.items,
        source_cart_id=order_input.source_cart_id,
        status="created",
    )
    ORDERS[order.id] = order
    return order


@app.get("/orders", response_model=List[Order], tags=["orders"])
def list_orders(
    customer_id: Optional[str] = Query(default=None, min_length=1),
) -> List[Order]:
    orders = list(ORDERS.values())
    if customer_id is not None:
        orders = [order for order in orders if order.customer_id == customer_id]
    return orders


@app.get("/orders/{order_id}", response_model=Order, tags=["orders"])
def get_order(order_id: str) -> Order:
    order = ORDERS.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    return order


@app.post("/orders/{order_id}/reserve", response_model=Order, tags=["orders"])
def reserve_order(order_id: str) -> Order:
    order = ORDERS.get(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    order.status = "inventory_pending"
    return order

