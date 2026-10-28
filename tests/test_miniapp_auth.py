"""Mini App auth checks: valid owner, forged signature, stale data, other user."""
import hashlib
import hmac
import json
from urllib.parse import urlencode

from app.miniapp import verify_init_data


def signed_init_data(token, user_id, timestamp):
    data = {
        "auth_date": str(timestamp),
        "query_id": "AAEtest",
        "user": json.dumps({"id": user_id, "first_name": "Owner"}, separators=(",", ":")),
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


def test_valid_owner():
    assert verify_init_data(signed_init_data("test-token", 123, 10000), "test-token", 123, now=10010)


def test_wrong_owner():
    assert not verify_init_data(signed_init_data("test-token", 456, 10000), "test-token", 123, now=10010)


def test_wrong_bot_token():
    assert not verify_init_data(signed_init_data("test-token", 123, 10000), "another-token", 123, now=10010)


def test_stale_auth():
    assert not verify_init_data(signed_init_data("test-token", 123, 10000), "test-token", 123, now=14000)


def test_tampered_data():
    raw = signed_init_data("test-token", 123, 10000)
    assert not verify_init_data(raw.replace("Owner", "Admin"), "test-token", 123, now=10010)


def test_duplicate_field():
    raw = signed_init_data("test-token", 123, 10000)
    assert not verify_init_data(raw + "&auth_date=10000", "test-token", 123, now=10010)
