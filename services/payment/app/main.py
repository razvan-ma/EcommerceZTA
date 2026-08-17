import os
import time
from contextlib import asynccontextmanager
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

try:
    import psycopg
except ImportError:  # Keep deterministic unit tests lightweight.
    psycopg = None


class AuthorizationCreate(BaseModel):
    order_id: str = Field(..., min_length=1)
    customer_id: str = Field(..., min_length=1)
    amount_cents: int = Field(..., ge=0)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    payment_method_token: str = Field(default="sandbox-token", min_length=1)


class Authorization(BaseModel):
    id: str
    order_id: str
    customer_id: str
    amount_cents: int
    currency: str
    status: str


AUTHORIZATIONS: Dict[str, Authorization] = {}
_sequence = 0


class InMemoryPaymentRepository:
    def initialize(self) -> None:
        return None

    def count(self) -> int:
        return len(AUTHORIZATIONS)

    def create_or_get(self, request: AuthorizationCreate) -> Authorization:
        global _sequence
        for authorization in AUTHORIZATIONS.values():
            if authorization.order_id == request.order_id:
                return authorization
        _sequence += 1
        authorization = Authorization(
            id=f"payment-{_sequence:04d}",
            order_id=request.order_id,
            customer_id=request.customer_id,
            amount_cents=request.amount_cents,
            currency=request.currency,
            status="authorized",
        )
        AUTHORIZATIONS[authorization.id] = authorization
        return authorization

    def get(self, authorization_id: str) -> Optional[Authorization]:
        return AUTHORIZATIONS.get(authorization_id)

    def list(self, order_id: Optional[str] = None) -> List[Authorization]:
        values = list(AUTHORIZATIONS.values())
        if order_id is not None:
            values = [authorization for authorization in values if authorization.order_id == order_id]
        return values


class PostgresPaymentRepository:
    def __init__(self, database_url: str) -> None:
        if psycopg is None:
            raise RuntimeError("psycopg is required when DATABASE_URL is configured")
        self.database_url = database_url

    def initialize(self) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS payment_authorizations (
                    id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL UNIQUE,
                    customer_id TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0),
                    currency CHAR(3) NOT NULL,
                    status TEXT NOT NULL
                )
                """
            )

    def count(self) -> int:
        with psycopg.connect(self.database_url) as connection:
            return connection.execute("SELECT COUNT(*) FROM payment_authorizations").fetchone()[0]

    def _from_row(self, row: tuple) -> Authorization:
        return Authorization(
            id=row[0],
            order_id=row[1],
            customer_id=row[2],
            amount_cents=row[3],
            currency=row[4],
            status=row[5],
        )

    def _next_id(self, connection) -> str:
        next_number = connection.execute(
            """
            SELECT COALESCE(MAX(CAST(SUBSTRING(id FROM 9) AS INTEGER)), 0) + 1
            FROM payment_authorizations WHERE id LIKE 'payment-%'
            """
        ).fetchone()[0]
        return f"payment-{next_number:04d}"

    def create_or_get(self, request: AuthorizationCreate) -> Authorization:
        with psycopg.connect(self.database_url) as connection:
            existing = connection.execute(
                "SELECT id, order_id, customer_id, amount_cents, currency, status "
                "FROM payment_authorizations WHERE order_id = %s",
                (request.order_id,),
            ).fetchone()
            if existing is not None:
                return self._from_row(existing)
            authorization_id = self._next_id(connection)
            connection.execute(
                """
                INSERT INTO payment_authorizations
                    (id, order_id, customer_id, amount_cents, currency, status)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    authorization_id,
                    request.order_id,
                    request.customer_id,
                    request.amount_cents,
                    request.currency,
                    "authorized",
                ),
            )
        return Authorization(
            id=authorization_id,
            order_id=request.order_id,
            customer_id=request.customer_id,
            amount_cents=request.amount_cents,
            currency=request.currency,
            status="authorized",
        )

    def get(self, authorization_id: str) -> Optional[Authorization]:
        with psycopg.connect(self.database_url) as connection:
            row = connection.execute(
                "SELECT id, order_id, customer_id, amount_cents, currency, status "
                "FROM payment_authorizations WHERE id = %s",
                (authorization_id,),
            ).fetchone()
        return None if row is None else self._from_row(row)

    def list(self, order_id: Optional[str] = None) -> List[Authorization]:
        query = (
            "SELECT id, order_id, customer_id, amount_cents, currency, status "
            "FROM payment_authorizations"
        )
        params = ()
        if order_id is not None:
            query += " WHERE order_id = %s"
            params = (order_id,)
        query += " ORDER BY id"
        with psycopg.connect(self.database_url) as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._from_row(row) for row in rows]


def _build_repository():
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return PostgresPaymentRepository(database_url)
    return InMemoryPaymentRepository()


@asynccontextmanager
async def lifespan(application: FastAPI):
    repository = application.state.payment_repository
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
    title="Zero-Trust E-commerce - Payment Service",
    version="0.1.0",
    description="M1 sandbox payment authorization service; no real card data is accepted.",
    lifespan=lifespan,
)
app.state.payment_repository = _build_repository()


@app.get("/", tags=["meta"])
def root() -> dict:
    return {"service": "payment", "version": app.version}


@app.get("/health/live", tags=["health"])
def liveness() -> dict:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def readiness() -> dict:
    return {"status": "ready", "authorization_count": app.state.payment_repository.count()}


@app.post(
    "/authorizations",
    response_model=Authorization,
    status_code=status.HTTP_201_CREATED,
    tags=["payments"],
)
def authorize_payment(request: AuthorizationCreate) -> Authorization:
    return app.state.payment_repository.create_or_get(request)


@app.get("/authorizations/{authorization_id}", response_model=Authorization, tags=["payments"])
def get_authorization(authorization_id: str) -> Authorization:
    authorization = app.state.payment_repository.get(authorization_id)
    if authorization is None:
        raise HTTPException(status_code=404, detail="payment authorization not found")
    return authorization


@app.get("/authorizations", response_model=List[Authorization], tags=["payments"])
def list_authorizations(order_id: Optional[str] = None) -> List[Authorization]:
    return app.state.payment_repository.list(order_id)
