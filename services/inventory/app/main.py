import os
import time
from contextlib import asynccontextmanager
from typing import Dict, List

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

try:
    import psycopg
except ImportError:  # Keep deterministic unit tests lightweight.
    psycopg = None


class StockItem(BaseModel):
    product_id: str = Field(..., min_length=1)
    available: int = Field(..., ge=0)
    reserved: int = Field(default=0, ge=0)


class ReservationItem(BaseModel):
    product_id: str = Field(..., min_length=1)
    quantity: int = Field(..., ge=1, le=100)


class ReservationCreate(BaseModel):
    order_id: str = Field(..., min_length=1)
    items: List[ReservationItem] = Field(..., min_length=1)


class Reservation(BaseModel):
    id: str
    order_id: str
    items: List[ReservationItem]
    status: str


INITIAL_STOCK = {
    "p-001": StockItem(product_id="p-001", available=10),
    "p-002": StockItem(product_id="p-002", available=25),
    "p-003": StockItem(product_id="p-003", available=5),
}
STOCK: Dict[str, StockItem] = {key: value.model_copy() for key, value in INITIAL_STOCK.items()}
RESERVATIONS: Dict[str, Reservation] = {}
_sequence = 0


class InventoryNotFound(Exception):
    pass


class InsufficientStock(Exception):
    pass


class InMemoryInventoryRepository:
    def initialize(self) -> None:
        return None

    def stock_count(self) -> int:
        return len(STOCK)

    def list_stock(self) -> List[StockItem]:
        return list(STOCK.values())

    def get_stock(self, product_id: str) -> StockItem:
        item = STOCK.get(product_id)
        if item is None:
            raise InventoryNotFound(product_id)
        return item

    def create_reservation(self, request: ReservationCreate) -> Reservation:
        for requested in request.items:
            stock = self.get_stock(requested.product_id)
            if stock.available < requested.quantity:
                raise InsufficientStock(requested.product_id)

        global _sequence
        _sequence += 1
        for requested in request.items:
            stock = STOCK[requested.product_id]
            stock.available -= requested.quantity
            stock.reserved += requested.quantity

        reservation = Reservation(
            id=f"reservation-{_sequence:04d}",
            order_id=request.order_id,
            items=request.items,
            status="reserved",
        )
        RESERVATIONS[reservation.id] = reservation
        return reservation

    def release_reservation(self, reservation_id: str) -> Reservation:
        reservation = RESERVATIONS.get(reservation_id)
        if reservation is None:
            raise InventoryNotFound(reservation_id)
        if reservation.status == "released":
            return reservation

        for reserved in reservation.items:
            stock = self.get_stock(reserved.product_id)
            stock.available += reserved.quantity
            stock.reserved -= reserved.quantity
        reservation.status = "released"
        return reservation


class PostgresInventoryRepository:
    def __init__(self, database_url: str) -> None:
        if psycopg is None:
            raise RuntimeError("psycopg is required when DATABASE_URL is configured")
        self.database_url = database_url

    def initialize(self) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS inventory_stock (
                    product_id TEXT PRIMARY KEY,
                    available INTEGER NOT NULL CHECK (available >= 0),
                    reserved INTEGER NOT NULL DEFAULT 0 CHECK (reserved >= 0)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reservations (
                    id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    status TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reservation_items (
                    reservation_id TEXT NOT NULL REFERENCES reservations(id) ON DELETE CASCADE,
                    product_id TEXT NOT NULL,
                    quantity INTEGER NOT NULL CHECK (quantity > 0),
                    PRIMARY KEY (reservation_id, product_id)
                )
                """
            )
            for product_id, item in INITIAL_STOCK.items():
                connection.execute(
                    """
                    INSERT INTO inventory_stock (product_id, available, reserved)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (product_id) DO NOTHING
                    """,
                    (product_id, item.available, item.reserved),
                )

    def stock_count(self) -> int:
        with psycopg.connect(self.database_url) as connection:
            return connection.execute("SELECT COUNT(*) FROM inventory_stock").fetchone()[0]

    def list_stock(self) -> List[StockItem]:
        with psycopg.connect(self.database_url) as connection:
            rows = connection.execute(
                "SELECT product_id, available, reserved FROM inventory_stock ORDER BY product_id"
            ).fetchall()
        return [StockItem(product_id=row[0], available=row[1], reserved=row[2]) for row in rows]

    def get_stock(self, product_id: str) -> StockItem:
        with psycopg.connect(self.database_url) as connection:
            row = connection.execute(
                "SELECT product_id, available, reserved FROM inventory_stock WHERE product_id = %s",
                (product_id,),
            ).fetchone()
        if row is None:
            raise InventoryNotFound(product_id)
        return StockItem(product_id=row[0], available=row[1], reserved=row[2])

    def _next_reservation_id(self, connection) -> str:
        next_number = connection.execute(
            """
            SELECT COALESCE(MAX(CAST(SUBSTRING(id FROM 13) AS INTEGER)), 0) + 1
            FROM reservations WHERE id LIKE 'reservation-%'
            """
        ).fetchone()[0]
        return f"reservation-{next_number:04d}"

    def create_reservation(self, request: ReservationCreate) -> Reservation:
        with psycopg.connect(self.database_url) as connection:
            for requested in request.items:
                row = connection.execute(
                    "SELECT available FROM inventory_stock WHERE product_id = %s FOR UPDATE",
                    (requested.product_id,),
                ).fetchone()
                if row is None:
                    raise InventoryNotFound(requested.product_id)
                if row[0] < requested.quantity:
                    raise InsufficientStock(requested.product_id)

            reservation_id = self._next_reservation_id(connection)
            connection.execute(
                "INSERT INTO reservations (id, order_id, status) VALUES (%s, %s, %s)",
                (reservation_id, request.order_id, "reserved"),
            )
            for requested in request.items:
                connection.execute(
                    """
                    UPDATE inventory_stock SET available = available - %s,
                        reserved = reserved + %s WHERE product_id = %s
                    """,
                    (requested.quantity, requested.quantity, requested.product_id),
                )
                connection.execute(
                    """
                    INSERT INTO reservation_items (reservation_id, product_id, quantity)
                    VALUES (%s, %s, %s)
                    """,
                    (reservation_id, requested.product_id, requested.quantity),
                )
        return Reservation(
            id=reservation_id,
            order_id=request.order_id,
            items=request.items,
            status="reserved",
        )

    def release_reservation(self, reservation_id: str) -> Reservation:
        with psycopg.connect(self.database_url) as connection:
            reservation = connection.execute(
                "SELECT id, order_id, status FROM reservations WHERE id = %s FOR UPDATE",
                (reservation_id,),
            ).fetchone()
            if reservation is None:
                raise InventoryNotFound(reservation_id)
            rows = connection.execute(
                "SELECT product_id, quantity FROM reservation_items WHERE reservation_id = %s",
                (reservation_id,),
            ).fetchall()
            items = [ReservationItem(product_id=row[0], quantity=row[1]) for row in rows]
            if reservation[2] == "released":
                return Reservation(
                    id=reservation[0], order_id=reservation[1], items=items, status=reservation[2]
                )
            for item in items:
                connection.execute(
                    """
                    UPDATE inventory_stock SET available = available + %s,
                        reserved = reserved - %s WHERE product_id = %s
                    """,
                    (item.quantity, item.quantity, item.product_id),
                )
            connection.execute(
                "UPDATE reservations SET status = %s WHERE id = %s",
                ("released", reservation_id),
            )
        return Reservation(
            id=reservation[0], order_id=reservation[1], items=items, status="released"
        )


def _build_repository():
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return PostgresInventoryRepository(database_url)
    return InMemoryInventoryRepository()


@asynccontextmanager
async def lifespan(application: FastAPI):
    repository = application.state.inventory_repository
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
    title="Zero-Trust E-commerce - Inventory Service",
    version="0.1.0",
    description="M1 deterministic stock and reservation service.",
    lifespan=lifespan,
)
app.state.inventory_repository = _build_repository()


@app.get("/", tags=["meta"])
def root() -> dict:
    return {"service": "inventory", "version": app.version}


@app.get("/health/live", tags=["health"])
def liveness() -> dict:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def readiness() -> dict:
    return {"status": "ready", "stock_items": app.state.inventory_repository.stock_count()}


@app.get("/inventory", response_model=List[StockItem], tags=["inventory"])
def list_inventory() -> List[StockItem]:
    return app.state.inventory_repository.list_stock()


@app.get("/inventory/{product_id}", response_model=StockItem, tags=["inventory"])
def get_stock(product_id: str) -> StockItem:
    try:
        return app.state.inventory_repository.get_stock(product_id)
    except InventoryNotFound as exc:
        raise HTTPException(status_code=404, detail="product stock not found") from exc


@app.post(
    "/reservations",
    response_model=Reservation,
    status_code=status.HTTP_201_CREATED,
    tags=["reservations"],
)
def create_reservation(request: ReservationCreate) -> Reservation:
    try:
        return app.state.inventory_repository.create_reservation(request)
    except InventoryNotFound as exc:
        raise HTTPException(
            status_code=404, detail=f"product stock not found: {exc}"
        ) from exc
    except InsufficientStock as exc:
        raise HTTPException(status_code=409, detail=f"insufficient stock: {exc}") from exc


@app.delete("/reservations/{reservation_id}", response_model=Reservation, tags=["reservations"])
def release_reservation(reservation_id: str) -> Reservation:
    try:
        return app.state.inventory_repository.release_reservation(reservation_id)
    except InventoryNotFound as exc:
        raise HTTPException(status_code=404, detail="reservation not found") from exc
