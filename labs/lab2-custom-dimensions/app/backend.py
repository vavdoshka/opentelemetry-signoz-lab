"""backend service for Lab 2: Lab 1's backend, plus a few OpenTelemetry API calls.

The OpenTelemetry Operator injects the agent, exactly as in Lab 1, so there is no
SDK setup here. This file only uses the API, to add what the agent can't know:
  - the price_order, list_orders and cpu_burn spans, and their attributes
  - cache.hit on the automatic server span
  - the orders.created, orders.value and cache.lookups metrics
"""

import logging
import os
import random
import time
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, HTTPException
from opentelemetry import metrics, trace
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")

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
cache_lookups = meter.create_counter(
    "cache.lookups", unit="{lookup}", description="Catalogue cache lookups, by hit or miss"
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
    coupon: str | None = None


PRICES = {"coffee": 3.5, "bagel": 2.25, "sandwich": 7.9, "cake": 4.75, "catering": 49.0}


def price_order(order: OrderIn) -> float:
    # Manual span: shows up as a child of the request span, with attributes.
    with tracer.start_as_current_span("price_order") as span:
        span.set_attribute("order.item", order.item)
        span.set_attribute("order.qty", order.qty)
        # Deliberate bug: pricing is very slow for this one item.
        time.sleep(1.5 if order.item == "catering" else random.uniform(0.005, 0.03))
        total = round(PRICES.get(order.item, 5.0) * order.qty, 2)
        # Deliberate bug: this 10% coupon makes the whole order free.
        if order.coupon == "SAVE10":
            span.set_attribute("order.coupon", order.coupon)
            total = 0.0
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


@app.get("/catalog")
def catalog(item: str) -> dict:
    # Deliberate problem: about a third of lookups miss the cache and take the slow path.
    hit = random.random() >= 0.33
    if not hit:
        time.sleep(0.8)
    trace.get_current_span().set_attribute("cache.hit", hit)
    cache_lookups.add(1, {"cache.hit": hit})
    return {"item": item, "price": PRICES.get(item, 5.0)}


@app.get("/work/slow")
def slow(ms: int = 0) -> dict:
    delay = ms / 1000 if ms else random.uniform(1.0, 3.0)
    log.info("slow work for %.2fs", delay)
    time.sleep(delay)
    return {"slept_s": round(delay, 3)}


@app.get("/work/fail")
def fail() -> dict:
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

