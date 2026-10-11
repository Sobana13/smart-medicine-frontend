from werkzeug.security import check_password_hash

from models import User
from tests.conftest import register


def test_register_login_logout_flow(client):
    assert register(client).status_code == 201
    assert client.get("/api/auth/me").get_json()["user"]["email"] == "pat@example.com"
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"email": "pat@example.com", "password": "wrong-password"}).status_code == 401
    ok = client.post("/api/auth/login", json={"email": "PAT@example.com", "password": "secret123"})
    assert ok.status_code == 200 and "password" not in str(ok.get_json())


def test_password_is_hashed(client):
    register(client)
    user = User.query.filter_by(email="pat@example.com").first()
    assert user.password_hash != "secret123"
    assert check_password_hash(user.password_hash, "secret123")


def test_duplicate_email_is_rejected(client, app):
    register(client)
    other = app.test_client()
    assert register(other, email="PAT@example.com").status_code == 409


def test_registration_validation(client):
    res = client.post("/api/auth/register", json={"name": "A", "email": "nope", "phone": "123", "password": "short"})
    assert res.status_code == 400
    assert set(res.get_json()["details"]) == {"name", "email", "phone", "password"}


def test_protected_routes_need_login(client):
    for path in ("/api/medicines", "/api/schedule", "/api/dashboard", "/api/notifications", "/api/settings", "/api/caregivers"):
        assert client.get(path).status_code == 401


def test_json_is_required(client):
    res = client.post("/api/auth/login", data="email=a@b.com&password=x")
    assert res.status_code == 400 and res.get_json()["code"] == "invalid_json"


def test_login_is_rate_limited(client):
    register(client, email="x@example.com")
    client.post("/api/auth/logout")
    for _ in range(5):
        client.post("/api/auth/login", json={"email": "x@example.com", "password": "bad-password"})
    assert client.post("/api/auth/login", json={"email": "x@example.com", "password": "secret123"}).status_code == 429
