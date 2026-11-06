"""backend service: orders API on Postgres, plus deliberate failure modes.

Instrumentation used (all standard OTel Python packages):
  - FastAPIInstrumentor  -> one SERVER span per request + http.server.* metrics
  - PsycopgInstrumentor  -> one CLIENT span per SQL statement (db.* attributes)
  - manual spans/metrics -> business logic (see `price_order`, `orders_created`)
"""

import logging
import os
import random
import time
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, HTTPException
from opentelemetry import metrics, trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from pydantic import BaseModel

from telemetry import setup_telemetry

setup_telemetry()
# Patches psycopg.connect so every connection it returns emits spans.
PsycopgInstrumentor().instrument(enable_commenter=False)

log = logging.getLogger("backend")
tracer = trace.get_tracer("lab.backend")
meter = metrics.get_meter("lab.backend")

# Custom business metrics.
orders_created = meter.create_counter(
    "orders.created", unit="{order}", description="Orders successfully stored"
)
order_value = meter.create_histogram(
    "orders.value", unit="USD", description="Value of each stored order"
)

DSN = os.environ["DATABASE_URL"]

def db() -> psycopg.Connection:
    return psycopg.connect(DSN, autocommit=True)


def init_schema() -> None:
    for attempt in range(30):
        try:
            with db() as conn:
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS orders (
                         id serial PRIMARY KEY,
                         item text NOT NULL,
                         qty int NOT NULL,
                         total numeric(10,2) NOT NULL,
                         created_at timestamptz NOT NULL DEFAULT now())"""
                )
            log.info("schema ready")
            return
        except psycopg.OperationalError as exc:
            log.warning("postgres not ready (attempt %d): %s", attempt + 1, exc)
            time.sleep(2)
    raise RuntimeError("postgres never became ready")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_schema()
    yield


app = FastAPI(title="backend", lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


class OrderIn(BaseModel):
    item: str
    qty: int


PRICES = {"coffee": 3.5, "bagel": 2.25, "sandwich": 7.9, "cake": 4.75}


def price_order(order: OrderIn) -> float:
    # Manual span: shows up as a child of the request span, with attributes.
    with tracer.start_as_current_span("price_order") as span:
        span.set_attribute("order.item", order.item)
        span.set_attribute("order.qty", order.qty)
        time.sleep(random.uniform(0.005, 0.03))  # pretend work
        total = round(PRICES.get(order.item, 5.0) * order.qty, 2)
        span.set_attribute("order.total", total)
        return total


@app.post("/orders")
def create_order(order: OrderIn) -> dict:
    total = price_order(order)
    with db() as conn:
        row = conn.execute(
            "INSERT INTO orders (item, qty, total) VALUES (%s, %s, %s) RETURNING id",
            (order.item, order.qty, total),
        ).fetchone()
    orders_created.add(1, {"order.item": order.item})
    order_value.record(total, {"order.item": order.item})
    log.info("order stored", extra={"order.id": row[0], "order.item": order.item, "order.total": total})
    return {"id": row[0], "total": total}


@app.get("/orders")
def list_orders() -> list[dict]:
    with tracer.start_as_current_span("list_orders") as span:
        with db() as conn:
            rows = conn.execute(
                "SELECT id, item, qty, total, created_at FROM orders ORDER BY id DESC LIMIT 20"
            ).fetchall()
        span.set_attribute("orders.returned", len(rows))
        log.info("list_order", extra={"total_orders": len(rows)})
        return [
            {"id": r[0], "item": r[1], "qty": r[2], "total": float(r[3]), "created_at": r[4].isoformat()}
            for r in rows
        ]


@app.get("/work/slow")
def slow(ms: int = 0) -> dict:
    delay = ms / 1000 if ms else random.uniform(1.0, 3.0)
    log.info("slow work for %.2fs", delay)
    time.sleep(delay)
    return {"slept_s": round(delay, 3)}


@app.get("/work/fail")
def fail() -> dict:
    # Unhandled exception -> 500. FastAPI instrumentation records it on the span.
    raise RuntimeError("backend exploded on purpose")


@app.get("/work/slow-query")
def slow_query(seconds: float = 2.0) -> dict:
    with db() as conn:
        conn.execute("SELECT pg_sleep(%s)", (seconds,))
    return {"query_s": seconds}


@app.get("/work/db-error")
def db_error() -> dict:
    try:
        with db() as conn:
            conn.execute("SELECT * FROM table_that_does_not_exist")
    except psycopg.errors.UndefinedTable as exc:
        # Handled: we log it and turn it into a 500 we control.
        log.error("query failed: %s", exc.diag.message_primary, exc_info=True)
        raise HTTPException(status_code=500, detail="database error") from exc
    return {}


@app.get("/work/cpu")
def cpu(seconds: float = 10.0) -> dict:
    with tracer.start_as_current_span("cpu_burn") as span:
        span.set_attribute("burn.seconds", seconds)
        end = time.monotonic() + seconds
        n = 0
        while time.monotonic() < end:
            n += sum(i * i for i in range(1000))
    log.warning("burned CPU for %.1fs", seconds)
    return {"burned_s": seconds}


# Server spans for every route, except the k8s probe endpoint (see
# OTEL_PYTHON_FASTAPI_EXCLUDED_URLS in labs/lab2-sdk/k8s/app.yaml).
FastAPIInstrumentor.instrument_app(app)
