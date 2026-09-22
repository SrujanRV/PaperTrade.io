#!/usr/bin/env python3
"""
test_wallet.py — Step 2a smoke test: DB models + wallet endpoints.

Uses FastAPI's dependency_overrides to inject an in-memory SQLite
session, so the real db.sqlite is never touched.

Run from the backend/ directory:
    python test_wallet.py
"""

from __future__ import annotations

import io
import sys
import os

# Force UTF-8 on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(__file__))

# ── In-memory test DB setup ───────────────────────────────────────────────────
from sqlalchemy import create_engine, inspect as sa_inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# StaticPool forces all connections to share the same underlying SQLite connection,
# which is required for ":memory:" databases (otherwise each new connection is blank).
_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)

# Import Base + ORM models to register mappers, then create tables
from database import Base
import models.orm  # noqa: F401  — side-effect: registers Wallet/Holding/Order/Transaction
Base.metadata.create_all(bind=_test_engine)

# ── FastAPI app + dependency override ─────────────────────────────────────────
from main import app
from database import get_db
from fastapi.testclient import TestClient


def _override_get_db():
    """Yield a session bound to the in-memory test engine."""
    db = _TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db
client = TestClient(app)

SEPARATOR = "─" * 65


def section(title: str):
    print(f"\n{SEPARATOR}\n  {title}\n{SEPARATOR}")


def check(condition: bool, msg: str):
    if not condition:
        raise AssertionError(msg)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_tables_created():
    section("1. DB tables created")
    inspector = sa_inspect(_test_engine)
    tables = set(inspector.get_table_names())
    expected = {"wallets", "holdings", "orders", "transactions"}
    for t in expected:
        icon = "✅" if t in tables else "❌"
        print(f"  {icon}  {t}")
    check(expected.issubset(tables), f"Missing tables: {expected - tables}")


def test_create_in_wallet():
    section("2. POST /api/wallet/setup — IN wallet (INR 500000)")
    r = client.post("/api/wallet/setup", json={"market": "IN", "starting_balance": 500000})
    print(f"  Status : {r.status_code}")
    data = r.json()
    print(f"  Payload: {data}")
    check(r.status_code == 201,       f"Expected 201, got {r.status_code}: {r.text}")
    check(data["market"]   == "IN",   "market should be IN")
    check(data["currency"] == "INR",  "currency should be INR")
    check(data["starting_balance"]     == 500000.0, "starting_balance mismatch")
    check(data["current_cash_balance"] == 500000.0, "current_cash_balance mismatch")
    check(data["holdings"] == [],     "holdings should be empty on setup")
    print("  ✅  IN wallet created correctly")


def test_create_us_wallet():
    section("3. POST /api/wallet/setup — US wallet (USD 10000)")
    r = client.post("/api/wallet/setup", json={"market": "US", "starting_balance": 10000})
    print(f"  Status : {r.status_code}")
    data = r.json()
    print(f"  Payload: {data}")
    check(r.status_code == 201,       f"Expected 201, got {r.status_code}: {r.text}")
    check(data["market"]   == "US",   "market should be US")
    check(data["currency"] == "USD",  "currency should be USD")
    check(data["starting_balance"]     == 10000.0, "starting_balance mismatch")
    check(data["current_cash_balance"] == 10000.0, "cash_balance mismatch")
    print("  ✅  US wallet created correctly")


def test_get_in_wallet():
    section("4. GET /api/wallet/IN")
    r = client.get("/api/wallet/IN")
    print(f"  Status : {r.status_code}")
    data = r.json()
    print(f"  market={data['market']}  currency={data['currency']}  "
          f"balance={data['current_cash_balance']}  holdings={data['holdings']}")
    check(r.status_code == 200,     f"Expected 200, got {r.status_code}")
    check(data["market"] == "IN",   "market should be IN")
    print("  ✅  GET IN wallet OK")


def test_get_us_wallet():
    section("5. GET /api/wallet/US")
    r = client.get("/api/wallet/US")
    print(f"  Status : {r.status_code}")
    data = r.json()
    print(f"  market={data['market']}  currency={data['currency']}  "
          f"balance={data['current_cash_balance']}  holdings={data['holdings']}")
    check(r.status_code == 200,     f"Expected 200, got {r.status_code}")
    check(data["market"] == "US",   "market should be US")
    print("  ✅  GET US wallet OK")


def test_reinit_wallet():
    section("6. POST /api/wallet/setup — re-init IN wallet with new balance")
    r = client.post("/api/wallet/setup", json={"market": "IN", "starting_balance": 1000000})
    data = r.json()
    print(f"  Status: {r.status_code}  new_balance={data.get('current_cash_balance')}")
    check(r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}")
    check(data["current_cash_balance"] == 1000000.0, "Re-init balance mismatch")
    check(data["holdings"] == [], "Holdings should be empty after re-init")

    r2 = client.get("/api/wallet/IN")
    check(r2.json()["current_cash_balance"] == 1000000.0, "GET should reflect new balance")
    print("  ✅  Wallet re-initialised (old data wiped, new balance confirmed)")


def test_get_unknown_market():
    section("7. GET /api/wallet/XX — expect 422 (path literal validation)")
    r = client.get("/api/wallet/XX")
    print(f"  Status: {r.status_code}  body={r.json()}")
    check(r.status_code == 422, f"Expected 422, got {r.status_code}")
    print("  ✅  Invalid market correctly rejected (422 Unprocessable Entity)")


def test_zero_balance_rejected():
    section("8. POST /api/wallet/setup balance=0 — expect 422")
    r = client.post("/api/wallet/setup", json={"market": "IN", "starting_balance": 0})
    print(f"  Status: {r.status_code}  body={r.json()}")
    check(r.status_code == 422, f"Expected 422, got {r.status_code}")
    print("  ✅  Zero balance correctly rejected (422 Unprocessable Entity)")


def test_negative_balance_rejected():
    section("9. POST /api/wallet/setup balance=-1000 — expect 422")
    r = client.post("/api/wallet/setup", json={"market": "IN", "starting_balance": -1000})
    print(f"  Status: {r.status_code}  body={r.json()}")
    check(r.status_code == 422, f"Expected 422, got {r.status_code}")
    print("  ✅  Negative balance correctly rejected (422 Unprocessable Entity)")


def test_update_wallet_balance():
    section("10. PATCH /api/wallet/IN/balance — adjust cash balance")
    r = client.patch("/api/wallet/IN/balance", json={"cash_balance": 750000.50})
    print(f"  Status: {r.status_code}  body={r.json()}")
    check(r.status_code == 200, f"Expected 200, got {r.status_code}")
    check(r.json()["current_cash_balance"] == 750000.50, "Updated cash balance mismatch")

    # Verify via GET
    r2 = client.get("/api/wallet/IN")
    check(r2.json()["current_cash_balance"] == 750000.50, "GET did not reflect updated balance")
    print("  ✅  Balance updated successfully without wiping wallet")


def test_delete_wallet():
    section("11. DELETE /api/wallet/IN — delete wallet and cascade")
    r = client.delete("/api/wallet/IN")
    print(f"  Status: {r.status_code}  body={r.json()}")
    check(r.status_code == 200, f"Expected 200, got {r.status_code}")
    check(r.json()["status"] == "deleted", "Expected status 'deleted'")

    # Verify GET returns 404
    r2 = client.get("/api/wallet/IN")
    check(r2.status_code == 404, f"Expected 404 after deletion, got {r2.status_code}")

    # Verify US wallet is untouched
    r_us = client.get("/api/wallet/US")
    check(r_us.status_code == 200, f"Expected US wallet to remain active, got {r_us.status_code}")
    print("  ✅  Wallet deleted cleanly; US wallet remains unaffected")


# ── Runner ────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "═" * 65)
    print("  PaperTrade — Step 2a: DB Models + Wallet Smoke Test")
    print("═" * 65)

    tests = [
        test_tables_created,
        test_create_in_wallet,
        test_create_us_wallet,
        test_get_in_wallet,
        test_get_us_wallet,
        test_reinit_wallet,
        test_get_unknown_market,
        test_zero_balance_rejected,
        test_negative_balance_rejected,
        test_update_wallet_balance,
        test_delete_wallet,
    ]

    failures = []
    for fn in tests:
        try:
            fn()
        except AssertionError as e:
            failures.append((fn.__name__, str(e)))
            print(f"  ❌  ASSERTION FAILED: {e}")
        except Exception as e:
            failures.append((fn.__name__, str(e)))
            print(f"  ❌  UNEXPECTED ERROR in {fn.__name__}: {e}")
            import traceback; traceback.print_exc()

    print("\n" + "═" * 65)
    if failures:
        print(f"  RESULT: {len(failures)} test(s) FAILED")
        for name, msg in failures:
            print(f"    ✗ {name}: {msg}")
        sys.exit(1)
    else:
        print(f"  RESULT: All {len(tests)} tests passed ✅")
    print("═" * 65 + "\n")


if __name__ == "__main__":
    main()

