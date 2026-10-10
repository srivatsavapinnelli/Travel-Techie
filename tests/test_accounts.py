"""
Tests for accounts, sessions, persistent bookings and saved plans (SQLite).
No internet needed. Run from the project folder:  python tests/test_accounts.py
"""
import json
import os
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["TT_DB_PATH"] = DB

from fastapi.testclient import TestClient

from db import accounts, database
from main import app

c = TestClient(app)
H = lambda t: {"Authorization": f"Bearer {t}"}


def register(name="Asha", email="asha@example.com", pw="correct-horse-9"):
    return c.post("/api/auth/register", json={"name": name, "email": email, "password": pw})


# 1) sign-up validation + success + duplicates
assert register(name=" ").status_code == 400
assert register(email="not-an-email").status_code == 400
assert register(pw="short").status_code == 400
assert register(pw="x" * 200).status_code == 400
r = register()
assert r.status_code == 200, r.text
asha = r.json()["data"]
assert asha["user"]["email"] == "asha@example.com" and len(asha["token"]) > 30 and len(asha["user"]["client_id"]) == 32
assert "pw_hash" not in json.dumps(asha) and "correct-horse-9" not in json.dumps(asha)
assert register(email="ASHA@Example.com").status_code == 409, "emails must be unique, ignoring case"
print("1) sign-up: validation, success, duplicate emails (case-insensitive) OK")

# 2) passwords are stored hashed; tokens only as a hash
raw = sqlite3.connect(DB)
pw_hash = raw.execute("SELECT pw_hash FROM users").fetchone()[0]
assert pw_hash.startswith("pbkdf2_sha256$") and "correct-horse-9" not in pw_hash
assert raw.execute("SELECT COUNT(*) FROM sessions WHERE token_hash = ?", (asha["token"],)).fetchone()[0] == 0
assert raw.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
print("2) password stored as salted PBKDF2 hash; session token stored only as a hash")

# 3) login / wrong password / unknown email give the same message
ok = c.post("/api/auth/login", json={"email": "Asha@example.com ", "password": "correct-horse-9"})
assert ok.status_code == 200 and ok.json()["data"]["user"]["client_id"] == asha["user"]["client_id"]
bad = c.post("/api/auth/login", json={"email": "asha@example.com", "password": "wrong-password"})
ghost = c.post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever123"})
assert bad.status_code == ghost.status_code == 401 and bad.json()["detail"] == ghost.json()["detail"]
assert c.post("/api/auth/login", json={"email": "", "password": ""}).status_code == 400
print("3) login OK; wrong password and unknown email are indistinguishable")

# 4) brute-force lockout (start from a clean slate: test 3 already used up one failed attempt)
accounts._failures.clear()
for i in range(accounts.LOCK_AFTER_FAILURES):
    r = c.post("/api/auth/login", json={"email": "asha@example.com", "password": f"guess-{i}-xx"})
assert r.status_code == 401
locked = c.post("/api/auth/login", json={"email": "asha@example.com", "password": "correct-horse-9"})
assert locked.status_code == 429, "even the right password must wait while locked"
accounts._failures["asha@example.com"] = (0, time.time() - 1)   # pretend the lock expired
assert c.post("/api/auth/login", json={"email": "asha@example.com", "password": "correct-horse-9"}).status_code == 200
print("4) 5 wrong passwords lock the account for a minute, then it recovers")

# 5) sessions: me / logout / bad token / expiry
tok = asha["token"]
assert c.get("/api/auth/me", headers=H(tok)).json()["data"]["name"] == "Asha"
assert c.get("/api/auth/me").status_code == 401
assert c.get("/api/auth/me", headers=H("garbage")).status_code == 401
assert c.post("/api/auth/logout", headers=H(tok)).status_code == 200
assert c.get("/api/auth/me", headers=H(tok)).status_code == 401, "logout must end the session"
tok2 = c.post("/api/auth/login", json={"email": "asha@example.com", "password": "correct-horse-9"}).json()["data"]["token"]
raw.execute("UPDATE sessions SET expires_at = '2000-01-01T00:00:00+00:00'"); raw.commit()
assert c.get("/api/auth/me", headers=H(tok2)).status_code == 401, "expired sessions must not work"
tok = c.post("/api/auth/login", json={"email": "asha@example.com", "password": "correct-horse-9"}).json()["data"]["token"]
print("5) sessions: me, logout, garbage token, expiry OK")

# 6) bookings: guest flow unchanged; claim moves guest bookings into the account; users are isolated
guest = "guest-browser-123"
for title, price in (("Flight HYD-GOI", 5400), ("Hotel in Goa", 9000)):
    r = c.post("/api/bookings", json={"client_id": guest, "vertical": "flight", "title": title, "price": price})
    assert r.status_code == 200
assert len(c.get("/api/bookings", params={"client_id": guest}).json()["data"]) == 2
claim = c.post("/api/auth/claim", json={"guest_client_id": guest}, headers=H(tok)).json()["data"]
assert claim["moved"] == 2
assert c.get("/api/bookings", params={"client_id": guest}).json()["data"] == []
assert c.post("/api/auth/claim", json={"guest_client_id": guest}, headers=H(tok)).json()["data"]["moved"] == 0
assert c.post("/api/auth/claim", json={"guest_client_id": guest}).status_code == 401
cid = asha["user"]["client_id"]
c.post("/api/bookings", json={"client_id": cid, "vertical": "hotel", "title": "Beach resort", "price": 12000})
trips = c.get("/api/me/trips", headers=H(tok)).json()["data"]
assert len(trips["bookings"]) == 3 and trips["plans"] == []
assert trips["bookings"][0]["title"] == "Beach resort", "newest first"
bob = register(name="Bob", email="bob@example.com").json()["data"]
assert c.get("/api/me/trips", headers=H(bob["token"])).json()["data"]["bookings"] == [], "users must not see each other's bookings"
bid = trips["bookings"][0]["booking_id"]
assert c.post(f"/api/bookings/{bid}/cancel", params={"client_id": bob["user"]["client_id"]}).status_code == 404
assert c.post(f"/api/bookings/{bid}/cancel", params={"client_id": cid}).json()["data"]["status"] == "cancelled"
print("6) bookings: guest flow works, claim moves them once, users isolated, cancel scoped")

# 7) saved plans
nav_plan = {"request": {"destination": "Jaipur", "budget": 60000}, "summary": {"days": [{"day": 1, "stops": [{"name": "Amber Fort"}]}]}}
sp = c.post("/api/me/plans", json={"kind": "navigator", "title": "Jaipur 3 days", "destination": "Jaipur", "payload": nav_plan}, headers=H(tok))
assert sp.status_code == 200, sp.text
pid = sp.json()["data"]["id"]
lst = c.get("/api/me/trips", headers=H(tok)).json()["data"]["plans"]
assert [p["id"] for p in lst] == [pid] and "payload" not in lst[0]
assert c.get(f"/api/me/plans/{pid}", headers=H(tok)).json()["data"]["payload"] == nav_plan
assert c.get(f"/api/me/plans/{pid}", headers=H(bob["token"])).status_code == 404, "plans are private"
assert c.delete(f"/api/me/plans/{pid}", headers=H(bob["token"])).status_code == 404
assert c.post("/api/me/plans", json={"kind": "navigator", "payload": {}}).status_code == 401
assert c.post("/api/me/plans", json={"kind": "hack", "title": "x", "payload": {}}, headers=H(tok)).status_code == 400
assert c.post("/api/me/plans", json={"kind": "ai_planner", "title": "big", "payload": {"x": "y" * 250_000}}, headers=H(tok)).status_code == 400
assert c.delete(f"/api/me/plans/{pid}", headers=H(tok)).status_code == 200
assert c.get(f"/api/me/plans/{pid}", headers=H(tok)).status_code == 404
print("7) plans: save, list (no payload), read, private to owner, bad kind / oversize rejected, delete")

# 8) plan limit
for i in range(accounts.MAX_PLANS_PER_USER):
    assert c.post("/api/me/plans", json={"kind": "ai_planner", "title": f"p{i}", "payload": {"i": i}}, headers=H(tok)).status_code == 200
assert c.post("/api/me/plans", json={"kind": "ai_planner", "title": "one too many", "payload": {}}, headers=H(tok)).status_code == 409
print("8) plan limit enforced (100)")

# 9) data survives a restart (close the connection, reopen the same file)
before = len(c.get("/api/me/trips", headers=H(tok)).json()["data"]["bookings"])
database._conn.close(); database._conn = None
after = c.get("/api/me/trips", headers=H(tok)).json()
assert len(after["data"]["bookings"]) == before and len(after["data"]["plans"]) == 100
assert c.get("/api/auth/me", headers=H(tok)).status_code == 200, "sessions survive restarts too"
print("9) bookings, plans and logins survive a restart")

# 10) the rest of the app still works and the frontend is still served after the new routes
assert c.get("/api/health").status_code == 200
assert "Travel Techie" in c.get("/").text
print("10) health + frontend still served")
print("\nALL ACCOUNT TESTS PASSED")
