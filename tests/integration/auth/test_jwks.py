"""`GET /.well-known/jwks.json` publishes the keys that verify the API's tokens (S6.1)"""

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient

from main import app
from src.auth.infra.jwks_routes import JwksRouter
from src.auth.infra.signing_keys import JwtKeys, jwt_keys
from tests.tokens import sign_token


def test_the_jwks_is_public_and_verifies_the_tokens_of_the_api():
    response = TestClient(app).get("/.well-known/jwks.json")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=300"
    jwks = response.json()
    assert [jwk["kid"] for jwk in jwks["keys"]] == list(jwt_keys().kids)
    assert all("d" not in jwk for jwk in jwks["keys"])

    # What another service does with it: verify a token by its kid
    token = sign_token({"sub": "1", "aud": "faclab-invoicing"})
    kid = jwt.get_unverified_header(token)["kid"]
    jwk = next(jwk for jwk in jwks["keys"] if jwk["kid"] == kid)
    key = jwt.PyJWK(jwk).key
    claims = jwt.decode(token, key, algorithms=["EdDSA"], audience="faclab-invoicing")
    assert claims["sub"] == "1"


def test_during_a_rotation_it_lists_both_keys():
    current, previous = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    keys = JwtKeys(current, [previous.public_key()])
    rotating = FastAPI()
    rotating.include_router(JwksRouter(keys).router)

    jwks = TestClient(rotating).get("/.well-known/jwks.json").json()

    assert [jwk["kid"] for jwk in jwks["keys"]] == list(keys.kids)
    assert len(jwks["keys"]) == 2
