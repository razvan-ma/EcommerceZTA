from typing import List

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field


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

app = FastAPI(
    title="Zero-Trust E-commerce - Product Service",
    version="0.1.0",
    description="M0 catalog service with deterministic data.",
)


@app.get("/", tags=["meta"])
def root() -> dict:
    return {"service": "product", "version": app.version}


@app.get("/health/live", tags=["health"])
def liveness() -> dict:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def readiness() -> dict:
    return {"status": "ready", "catalog_size": len(PRODUCTS)}


@app.get("/products", response_model=ProductList, tags=["products"])
def list_products(
    limit: int = Query(default=20, ge=1, le=100),
    available_only: bool = True,
) -> ProductList:
    products = [product for product in CATALOG if not available_only or product.available]
    items = products[:limit]
    return ProductList(items=items, count=len(items))


@app.get("/products/{product_id}", response_model=Product, tags=["products"])
def get_product(product_id: str) -> Product:
    product = PRODUCTS.get(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")
    return product

