"""Manual verification helper (not part of the app or test suite).

Generates an RSA keypair, serves a fake JWKS endpoint over local HTTP, and
prints a signed JWT that `app/core/clerk_auth.py` will accept when
`CLERK_JWT_ISSUER` is pointed at that local JWKS server. Lets you smoke-test
authenticated endpoints with `curl` without a real Clerk session.

Usage:
    python scripts/mint_test_jwt.py [clerk_user_id]

Then in another terminal:
    CLERK_JWT_ISSUER=http://127.0.0.1:<printed-port> uvicorn app.main:app --port 8000

Ctrl+C to stop the fake JWKS server when done.
"""

from __future__ import annotations

import http.server
import json
import sys
import threading
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt
from jose.utils import base64url_encode


def main() -> None:
    clerk_user_id = sys.argv[1] if len(sys.argv) > 1 else "user_test_manual_verification"

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_numbers = private_key.public_key().public_numbers()
    n = base64url_encode(public_numbers.n.to_bytes(256, "big")).decode()
    e = base64url_encode(public_numbers.e.to_bytes(3, "big")).decode()

    kid = "test-key-1"
    jwks = {"keys": [{"kty": "RSA", "kid": kid, "use": "sig", "alg": "RS256", "n": n, "e": e}]}

    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/.well-known/jwks.json":
                body = json.dumps(jwks).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args) -> None:  # silence default request logging
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    issuer = f"http://127.0.0.1:{port}"
    now = int(time.time())
    token = jwt.encode(
        {"sub": clerk_user_id, "iss": issuer, "iat": now, "exp": now + 3600},
        pem,
        algorithm="RS256",
        headers={"kid": kid},
    )

    print(f"Fake JWKS server running at {issuer}/.well-known/jwks.json")
    print(f"Set:  export CLERK_JWT_ISSUER={issuer}")
    print("Then in another terminal (same repo/venv):")
    print(f'  CLERK_JWT_ISSUER={issuer} uvicorn app.main:app --host 0.0.0.0 --port 8000')
    print()
    print(f"Bearer token (sub={clerk_user_id}):")
    print(token)
    print()
    print("Keeping JWKS server alive — Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
