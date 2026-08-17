import os
import time
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

try:
    import psycopg
except ImportError:  # Keep deterministic unit tests lightweight.
    psycopg = None


class Product(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str
    price_cents: int = Field(..., ge=0)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    available: bool = True


class ProductList(BaseModel):
    items: List[Product]
    count: int = Field(..., ge=0)


CATALOG = [
    Product(
        id="p-001",
        name="Zero Trust Hoodie",
        description="A catalog item for the platform demonstrator.",
        price_cents=4999,
    ),
    Product(
        id="p-002",
        name="Encrypted Notebook",
        description="A second deterministic product for contract tests.",
        price_cents=1299,
    ),
    Product(
        id="p-003",
        name="Service Identity Mug",
        description="A third deterministic product for pagination checks.",
        price_cents=1599,
    ),
]

PRODUCTS = {product.id: product for product in CATALOG}

PRODUCT_COLUMNS = ("id", "name", "description", "price_cents", "currency", "available")


def _product_from_row(row: tuple) -> Product:
    return Product(**dict(zip(PRODUCT_COLUMNS, row)))


class InMemoryProductRepository:
    def __init__(self, products: List[Product]) -> None:
        self.products = {product.id: product for product in products}

    def initialize(self) -> None:
        return None

    def list(self, limit: int, available_only: bool) -> List[Product]:
        products = list(self.products.values())
        if available_only:
            products = [product for product in products if product.available]
        return products[:limit]

    def count(self) -> int:
        return len(self.products)

    def get(self, product_id: str) -> Optional[Product]:
        return self.products.get(product_id)


class PostgresProductRepository:
    def __init__(self, database_url: str) -> None:
        if psycopg is None:
            raise RuntimeError("psycopg is required when DATABASE_URL is configured")
        self.database_url = database_url

    def initialize(self) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS products (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
                    currency CHAR(3) NOT NULL,
                    available BOOLEAN NOT NULL DEFAULT TRUE
                )
                """
            )
            for product in CATALOG:
                connection.execute(
                    """
                    INSERT INTO products (id, name, description, price_cents, currency, available)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        product.id,
                        product.name,
                        product.description,
                        product.price_cents,
                        product.currency,
                        product.available,
                    ),
                )

    def list(self, limit: int, available_only: bool) -> List[Product]:
        query = "SELECT id, name, description, price_cents, currency, available FROM products"
        if available_only:
            query += " WHERE available = TRUE"
        query += " ORDER BY id LIMIT %s"
        with psycopg.connect(self.database_url) as connection:
            rows = connection.execute(query, (limit,)).fetchall()
        return [_product_from_row(row) for row in rows]

    def count(self) -> int:
        with psycopg.connect(self.database_url) as connection:
            return connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]

    def get(self, product_id: str) -> Optional[Product]:
        with psycopg.connect(self.database_url) as connection:
            row = connection.execute(
                "SELECT id, name, description, price_cents, currency, available "
                "FROM products WHERE id = %s",
                (product_id,),
            ).fetchone()
        return None if row is None else _product_from_row(row)


def _build_repository():
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return PostgresProductRepository(database_url)
    return InMemoryProductRepository(CATALOG)


@asynccontextmanager
async def lifespan(application: FastAPI):
    repository = application.state.product_repository
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
    title="Zero-Trust E-commerce - Product Service",
    version="0.1.0",
    description="M0 catalog service with deterministic data.",
    lifespan=lifespan,
)
app.state.product_repository = _build_repository()


@app.get("/", tags=["meta"])
def root() -> dict:
    return {"service": "product", "version": app.version}


@app.get("/health/live", tags=["health"])
def liveness() -> dict:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def readiness() -> dict:
    return {"status": "ready", "catalog_size": app.state.product_repository.count()}


@app.get("/products", response_model=ProductList, tags=["products"])
def list_products(
    limit: int = Query(default=20, ge=1, le=100),
    available_only: bool = True,
) -> ProductList:
    items = app.state.product_repository.list(limit, available_only)
    return ProductList(items=items, count=len(items))


@app.get("/products/{product_id}", response_model=Product, tags=["products"])
def get_product(product_id: str) -> Product:
    product = app.state.product_repository.get(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")
    return product
