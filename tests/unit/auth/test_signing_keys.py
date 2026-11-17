import base64
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.auth.infra.signing_keys import (
    DEVELOPMENT_KID,
    JwtKeys,
    development_key,
    key_id,
)


def _private_pem(key) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def _public_pem(key) -> str:
    return (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )


def _config(environment: str = "production", **settings: Any) -> Any:
    values: dict[str, Any] = {
        "ENVIRONMENT": environment,
        "JWT_PRIVATE_KEY": "",
        "JWT_PRIVATE_KEY_FILE": "",
        "JWT_PUBLIC_KEYS": "",
        "JWT_PUBLIC_KEYS_FILE": "",
    }
    values.update(settings)
    return SimpleNamespace(**values)


def test_the_kid_is_the_rfc_7638_thumbprint():
    # RFC 8037, appendix A: the Ed25519 key and its thumbprint
    seed = base64.urlsafe_b64decode("nWGxne_9WmC6hEr0kuwsxERJxWl7MmkZcDusAxyuf2A=")
    key = Ed25519PrivateKey.from_private_bytes(seed).public_key()

    assert key_id(key) == "kPrK_qmxVWaYVA9wwBF6Iuo3vVzz7TxHCTwXBygrS4k"


def test_the_jwks_publishes_only_the_public_part_of_each_key():
    signing, previous = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    keys = JwtKeys(signing, [previous.public_key(), signing.public_key()])

    jwks = keys.jwks()["keys"]

    assert [jwk["kid"] for jwk in jwks] == [
        key_id(signing.public_key()),
        key_id(previous.public_key()),
    ]
    for jwk in jwks:
        assert set(jwk) == {"kty", "crv", "x", "kid", "alg", "use"}
        assert (jwk["kty"], jwk["crv"], jwk["alg"], jwk["use"]) == (
            "OKP",
            "Ed25519",
            "EdDSA",
            "sig",
        )
    assert keys.verification_key(key_id(previous.public_key())) is not None
    assert keys.verification_key("unknown") is None


def test_reads_the_signing_key_and_the_extra_public_keys_from_variables():
    signing, previous, next_ = (Ed25519PrivateKey.generate() for _ in range(3))

    keys = JwtKeys.from_config(
        _config(
            JWT_PRIVATE_KEY=_private_pem(signing),
            JWT_PUBLIC_KEYS=_public_pem(previous) + _public_pem(next_),
        )
    )

    assert keys.signing_kid == key_id(signing.public_key())
    assert keys.kids == tuple(
        key_id(key.public_key()) for key in (signing, previous, next_)
    )


def test_a_variable_may_carry_its_newlines_escaped():
    signing = Ed25519PrivateKey.generate()
    one_line = _private_pem(signing).replace("\n", "\\n")

    keys = JwtKeys.from_config(_config(JWT_PRIVATE_KEY=one_line))

    assert keys.signing_kid == key_id(signing.public_key())


def test_reads_the_keys_from_files(tmp_path):
    signing, previous = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    private_file = tmp_path / "signing.pem"
    private_file.write_text(_private_pem(signing))
    public_file = tmp_path / "public.pem"
    public_file.write_text(_public_pem(previous))

    keys = JwtKeys.from_config(
        _config(
            JWT_PRIVATE_KEY_FILE=str(private_file),
            JWT_PUBLIC_KEYS_FILE=str(public_file),
        )
    )

    assert keys.kids == (
        key_id(signing.public_key()),
        key_id(previous.public_key()),
    )


def test_locally_without_a_key_the_development_key_signs():
    keys = JwtKeys.from_config(_config("local"))

    assert keys.signing_kid == DEVELOPMENT_KID
    assert JwtKeys.from_config(_config("local")).jwks() == keys.jwks()


@pytest.mark.parametrize(
    "settings",
    [
        {"JWT_PRIVATE_KEY": _private_pem(development_key())},
        {
            "JWT_PRIVATE_KEY": _private_pem(Ed25519PrivateKey.generate()),
            "JWT_PUBLIC_KEYS": _public_pem(development_key()),
        },
    ],
    ids=["signing", "published"],
)
def test_the_development_key_is_refused_outside_local(settings):
    with pytest.raises(RuntimeError, match="development JWT key"):
        JwtKeys.from_config(_config("staging", **settings))


def test_outside_local_a_signing_key_is_required():
    with pytest.raises(RuntimeError, match="JWT_PRIVATE_KEY or JWT_PRIVATE_KEY_FILE"):
        JwtKeys.from_config(_config("production"))


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        (
            {"JWT_PRIVATE_KEY": "x", "JWT_PRIVATE_KEY_FILE": "/run/secrets/jwt"},
            "Set JWT_PRIVATE_KEY or JWT_PRIVATE_KEY_FILE, not both",
        ),
        ({"JWT_PRIVATE_KEY_FILE": "/does/not/exist.pem"}, "can't be read"),
        ({"JWT_PRIVATE_KEY": "not a key"}, "not an unencrypted PEM private key"),
        (
            {"JWT_PRIVATE_KEY": _private_pem(generate_private_key(SECP256R1()))},
            "must be an Ed25519 key",
        ),
        (
            {
                "JWT_PRIVATE_KEY": _private_pem(Ed25519PrivateKey.generate()),
                "JWT_PUBLIC_KEYS": "nothing here",
            },
            "holds no PEM public key",
        ),
        (
            {
                "JWT_PRIVATE_KEY": _private_pem(Ed25519PrivateKey.generate()),
                "JWT_PUBLIC_KEYS": _public_pem(generate_private_key(SECP256R1())),
            },
            "must hold Ed25519 keys",
        ),
    ],
    ids=["both", "missing-file", "garbage", "not-ed25519", "no-pem", "public-ec"],
)
def test_a_bad_key_stops_the_startup_without_showing_it(settings, message):
    with pytest.raises(RuntimeError, match=message) as exc:
        JwtKeys.from_config(_config(**settings))

    assert "PRIVATE KEY-----" not in str(exc.value)
