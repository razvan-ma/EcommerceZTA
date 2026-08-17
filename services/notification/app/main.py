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


class OrderEvent(BaseModel):
    order_id: str = Field(..., min_length=1)
    customer_id: str = Field(..., min_length=1)
    event_type: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1)


class Notification(BaseModel):
    id: str
    order_id: str
    customer_id: str
    event_type: str
    status: str
    delivery_status: str


NOTIFICATIONS: Dict[str, Notification] = {}
_sequence = 0


class InMemoryNotificationRepository:
    def initialize(self) -> None:
        return None

    def count(self) -> int:
        return len(NOTIFICATIONS)

    def publish(self, event: OrderEvent) -> Notification:
        global _sequence
        _sequence += 1
        notification = Notification(
            id=f"notification-{_sequence:04d}",
            order_id=event.order_id,
            customer_id=event.customer_id,
            event_type=event.event_type,
            status=event.status,
            delivery_status="queued",
        )
        NOTIFICATIONS[notification.id] = notification
        return notification

    def get(self, notification_id: str) -> Optional[Notification]:
        return NOTIFICATIONS.get(notification_id)

    def list(self, customer_id: Optional[str] = None) -> List[Notification]:
        values = list(NOTIFICATIONS.values())
        if customer_id is not None:
            values = [notification for notification in values if notification.customer_id == customer_id]
        return values


class PostgresNotificationRepository:
    def __init__(self, database_url: str) -> None:
        if psycopg is None:
            raise RuntimeError("psycopg is required when DATABASE_URL is configured")
        self.database_url = database_url

    def initialize(self) -> None:
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS notifications (
                    id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    delivery_status TEXT NOT NULL
                )
                """
            )

    def count(self) -> int:
        with psycopg.connect(self.database_url) as connection:
            return connection.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]

    def _from_row(self, row: tuple) -> Notification:
        return Notification(
            id=row[0],
            order_id=row[1],
            customer_id=row[2],
            event_type=row[3],
            status=row[4],
            delivery_status=row[5],
        )

    def _next_id(self, connection) -> str:
        next_number = connection.execute(
            """
            SELECT COALESCE(MAX(CAST(SUBSTRING(id FROM 14) AS INTEGER)), 0) + 1
            FROM notifications WHERE id LIKE 'notification-%'
            """
        ).fetchone()[0]
        return f"notification-{next_number:04d}"

    def publish(self, event: OrderEvent) -> Notification:
        with psycopg.connect(self.database_url) as connection:
            notification_id = self._next_id(connection)
            connection.execute(
                """
                INSERT INTO notifications
                    (id, order_id, customer_id, event_type, status, delivery_status)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    notification_id,
                    event.order_id,
                    event.customer_id,
                    event.event_type,
                    event.status,
                    "queued",
                ),
            )
        return Notification(
            id=notification_id,
            order_id=event.order_id,
            customer_id=event.customer_id,
            event_type=event.event_type,
            status=event.status,
            delivery_status="queued",
        )

    def get(self, notification_id: str) -> Optional[Notification]:
        with psycopg.connect(self.database_url) as connection:
            row = connection.execute(
                "SELECT id, order_id, customer_id, event_type, status, delivery_status "
                "FROM notifications WHERE id = %s",
                (notification_id,),
            ).fetchone()
        return None if row is None else self._from_row(row)

    def list(self, customer_id: Optional[str] = None) -> List[Notification]:
        query = (
            "SELECT id, order_id, customer_id, event_type, status, delivery_status "
            "FROM notifications"
        )
        params = ()
        if customer_id is not None:
            query += " WHERE customer_id = %s"
            params = (customer_id,)
        query += " ORDER BY id"
        with psycopg.connect(self.database_url) as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._from_row(row) for row in rows]


def _build_repository():
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return PostgresNotificationRepository(database_url)
    return InMemoryNotificationRepository()


@asynccontextmanager
async def lifespan(application: FastAPI):
    repository = application.state.notification_repository
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
    title="Zero-Trust E-commerce - Notification Service",
    version="0.1.0",
    description="M1 deterministic order-event notification service.",
    lifespan=lifespan,
)
app.state.notification_repository = _build_repository()


@app.get("/", tags=["meta"])
def root() -> dict:
    return {"service": "notification", "version": app.version}


@app.get("/health/live", tags=["health"])
def liveness() -> dict:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def readiness() -> dict:
    return {"status": "ready", "notification_count": app.state.notification_repository.count()}


@app.post(
    "/events/order",
    response_model=Notification,
    status_code=status.HTTP_201_CREATED,
    tags=["notifications"],
)
def publish_order_event(event: OrderEvent) -> Notification:
    return app.state.notification_repository.publish(event)


@app.get("/notifications/{notification_id}", response_model=Notification, tags=["notifications"])
def get_notification(notification_id: str) -> Notification:
    notification = app.state.notification_repository.get(notification_id)
    if notification is None:
        raise HTTPException(status_code=404, detail="notification not found")
    return notification


@app.get("/notifications", response_model=List[Notification], tags=["notifications"])
def list_notifications(customer_id: Optional[str] = None) -> List[Notification]:
    return app.state.notification_repository.list(customer_id)
