import os
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

try:
    import jwt
except ImportError:  # Optional for the local unauthenticated test mode.
    jwt = None


class CartItemInput(BaseModel):
    product_id: str = Field(..., min_length=1)
    quantity: int = Field(..., ge=1, le=100)


class LoginInput(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class KeycloakAuth:
    def __init__(self) -> None:
        self.required = os.getenv("AUTH_REQUIRED", "false").lower() == "true"
        self.issuer = os.getenv("KEYCLOAK_ISSUER", "").rstrip("/")
        self.jwks_url = os.getenv("KEYCLOAK_JWKS_URL", "")
        self.client_id = os.getenv("KEYCLOAK_CLIENT_ID", "ecommerce-ui")
        self._jwks: dict[str, Any] = {}
        self._jwks_loaded_at = 0.0

    async def _load_keys(self) -> dict[str, Any]:
        if self._jwks and time.time() - self._jwks_loaded_at < 300:
            return self._jwks
        if not self.jwks_url:
            raise HTTPException(status_code=503, detail="identity provider is not configured")
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(self.jwks_url)
        response.raise_for_status()
        self._jwks = {key["kid"]: key for key in response.json().get("keys", [])}
        self._jwks_loaded_at = time.time()
        return self._jwks

    async def authenticate(self, request: Request) -> dict[str, Any]:
        header = request.headers.get("Authorization", "")
        if not self.required and not header:
            return {"preferred_username": request.path_params.get("customer_id", "customer-1")}
        if not header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Bearer token required")
        token = header.removeprefix("Bearer ").strip()
        try:
            if jwt is None:
                raise HTTPException(status_code=503, detail="JWT support is not installed")
            token_header = jwt.get_unverified_header(token)
            keys = await self._load_keys()
            jwk = keys.get(token_header.get("kid"))
            if jwk is None:
                raise HTTPException(status_code=401, detail="unknown token key")
            claims = jwt.decode(
                token,
                jwt.algorithms.RSAAlgorithm.from_jwk(jwk),
                algorithms=["RS256"],
                issuer=self.issuer,
                options={"verify_aud": False},
            )
            if claims.get("azp") != self.client_id:
                raise HTTPException(status_code=403, detail="token was not issued to this client")
            if not claims.get("sub"):
                raise HTTPException(status_code=403, detail="token has no subject")
            return claims
        except HTTPException:
            raise
        except (jwt.PyJWTError, httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=401, detail="invalid access token") from exc

    async def login(self, credentials: LoginInput) -> dict[str, Any]:
        token_url = os.getenv("KEYCLOAK_TOKEN_URL", "")
        if not token_url:
            raise HTTPException(status_code=503, detail="identity provider is not configured")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    token_url,
                    data={
                        "grant_type": "password",
                        "client_id": self.client_id,
                        "username": credentials.username,
                        "password": credentials.password,
                    },
                )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=401, detail="invalid username or password") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=503, detail="identity provider unavailable") from exc


class ServiceClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=5.0) as client:
                response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            try:
                detail = exc.response.json().get("detail", "upstream request failed")
            except ValueError:
                detail = "upstream request failed"
            raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=502, detail="upstream service unavailable") from exc


app = FastAPI(
    title="Zero-Trust E-commerce - Web UI",
    version="0.1.0",
    description="Bare-bones browser UI for the current e-commerce baseline.",
)
app.state.auth = KeycloakAuth()
app.state.product_client = ServiceClient(os.getenv("PRODUCT_SERVICE_URL", "http://product:8000"))
app.state.cart_client = ServiceClient(os.getenv("CART_SERVICE_URL", "http://cart:8000"))
INDEX_HTML = (
    Path(__file__).resolve().parent / "static" / "index.html"
).read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index() -> HTMLResponse:
    return HTMLResponse(INDEX_HTML)


@app.get("/health/live", tags=["health"])
def liveness() -> dict:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def readiness() -> dict:
    return {"status": "ready"}


@app.post("/api/login", tags=["auth"])
async def login(credentials: LoginInput) -> dict[str, Any]:
    return await app.state.auth.login(credentials)


async def _authenticated_customer(request: Request, customer_id: str) -> dict[str, Any]:
    claims = await request.app.state.auth.authenticate(request)
    username = claims.get("preferred_username") or claims.get("sub")
    if username != customer_id:
        raise HTTPException(status_code=403, detail="customer does not own this cart")
    return claims


@app.get("/api/products", tags=["ui"])
async def products(request: Request) -> Any:
    await request.app.state.auth.authenticate(request)
    return await app.state.product_client.request("GET", "/products")


@app.get("/api/cart/{customer_id}", tags=["ui"])
async def cart(customer_id: str, request: Request) -> Any:
    await _authenticated_customer(request, customer_id)
    return await app.state.cart_client.request("GET", f"/carts/{customer_id}")


@app.put("/api/cart/{customer_id}/items", status_code=status.HTTP_200_OK, tags=["ui"])
async def add_cart_item(customer_id: str, item: CartItemInput, request: Request) -> Any:
    await _authenticated_customer(request, customer_id)
    return await app.state.cart_client.request(
        "PUT", f"/carts/{customer_id}/items", json=item.model_dump()
    )


@app.delete("/api/cart/{customer_id}/items/{product_id}", tags=["ui"])
async def remove_cart_item(customer_id: str, product_id: str, request: Request) -> Any:
    await _authenticated_customer(request, customer_id)
    return await app.state.cart_client.request(
        "DELETE", f"/carts/{customer_id}/items/{product_id}"
    )


@app.post("/api/cart/{customer_id}/checkout", status_code=status.HTTP_201_CREATED, tags=["ui"])
async def checkout(customer_id: str, request: Request) -> Any:
    await _authenticated_customer(request, customer_id)
    return await app.state.cart_client.request("POST", f"/carts/{customer_id}/checkout")
