from __future__ import annotations

from pathlib import Path
import hashlib
import hmac
import json
import secrets
import time
import base64
import os

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
AUTH_FILE = DATA_DIR / "auth.json"
ACCESS_FILE = BASE_DIR.parent / "ACESSO_CHAPA_ID.txt"

SESSION_HOURS = 12

ENV_USER = "CHAPA_ID_USER"
ENV_PASSWORD = "CHAPA_ID_PASSWORD"
ENV_SESSION_SECRET = "CHAPA_ID_SESSION_SECRET"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _pbkdf2(password: str, salt: bytes) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        250_000,
    )
    return _b64(digest)


def _env_auth():
    username = os.getenv(ENV_USER, "").strip()
    password = os.getenv(ENV_PASSWORD, "")

    if username and password:
        return username, password

    return None


def _env_session_secret() -> bytes | None:
    value = os.getenv(ENV_SESSION_SECRET, "").strip()

    if value:
        return hashlib.sha256(value.encode("utf-8")).digest()

    auth = _env_auth()

    if auth:
        username, password = auth
        value = f"chapa-id|{username}|{password}|session-v1"
        return hashlib.sha256(value.encode("utf-8")).digest()

    return None


def ensure_auth():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if _env_auth():
        return

    if AUTH_FILE.exists():
        return

    username = "chapaid"
    password = "Chapa-" + secrets.token_urlsafe(8)

    salt = secrets.token_bytes(16)
    secret = secrets.token_bytes(32)

    data = {
        "username": username,
        "salt": _b64(salt),
        "password_hash": _pbkdf2(password, salt),
        "session_secret": _b64(secret),
    }

    AUTH_FILE.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8",
    )

    ACCESS_FILE.write_text(
        "CHAPA ID - ACESSO DO TESTE\n"
        "==========================\n"
        f"Usuario: {username}\n"
        f"Senha: {password}\n\n"
        "IMPORTANTE:\n"
        "- Este arquivo contem a senha do sistema.\n"
        "- Nao envie este arquivo junto com a URL publica.\n"
        "- A URL do tunel muda a cada execucao.\n",
        encoding="utf-8",
    )


def _load():
    ensure_auth()
    return json.loads(
        AUTH_FILE.read_text(encoding="utf-8")
    )


def verify_password(username: str, password: str) -> bool:
    env_auth = _env_auth()

    if env_auth:
        expected_user, expected_password = env_auth
        return (
            hmac.compare_digest(str(username), expected_user)
            and hmac.compare_digest(str(password), expected_password)
        )

    d = _load()

    if not hmac.compare_digest(username, d["username"]):
        return False

    salt = base64.urlsafe_b64decode(d["salt"] + "==")
    got = _pbkdf2(password, salt)

    return hmac.compare_digest(
        got,
        d["password_hash"],
    )


def _session_secret() -> bytes:
    env_secret = _env_session_secret()

    if env_secret is not None:
        return env_secret

    d = _load()

    return base64.urlsafe_b64decode(
        d["session_secret"] + "=="
    )


def create_session(username: str) -> str:
    exp = int(time.time() + SESSION_HOURS * 3600)
    payload = f"{username}|{exp}"

    secret = _session_secret()

    sig = hmac.new(
        secret,
        payload.encode(),
        hashlib.sha256,
    ).digest()

    return _b64(payload.encode()) + "." + _b64(sig)


def verify_session(token: str | None) -> str | None:
    if not token or "." not in token:
        return None

    try:
        p64, s64 = token.split(".", 1)

        payload = base64.urlsafe_b64decode(
            p64 + "=="
        ).decode()

        sig = base64.urlsafe_b64decode(
            s64 + "=="
        )

        username, exp_s = payload.rsplit("|", 1)

        if int(exp_s) < int(time.time()):
            return None

        env_auth = _env_auth()

        if env_auth:
            expected_username, _ = env_auth

            if not hmac.compare_digest(
                username,
                expected_username,
            ):
                return None

        else:
            d = _load()

            if username != d["username"]:
                return None

        secret = _session_secret()

        expected = hmac.new(
            secret,
            payload.encode(),
            hashlib.sha256,
        ).digest()

        if not hmac.compare_digest(
            sig,
            expected,
        ):
            return None

        return username

    except Exception:
        return None