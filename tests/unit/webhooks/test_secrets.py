"""The webhooks' secrets, encrypted with the environment's master key (S6.4)."""

from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from src.webhooks.infra.secrets import DEVELOPMENT_KEY, FernetSecretBox


def _config(environment="production", keys="", path=""):
    return SimpleNamespace(
        ENVIRONMENT=environment,
        SECRET_ENCRYPTION_KEYS=keys,
        SECRET_ENCRYPTION_KEYS_FILE=path,
    )


def test_a_sealed_secret_is_not_the_secret_and_opens_back():
    box = FernetSecretBox([Fernet.generate_key().decode()])

    sealed = box.seal("whsec_abc")

    assert "whsec_abc" not in sealed
    assert box.open(sealed) == "whsec_abc"


def test_the_master_key_rotates_keeping_the_old_one_to_decrypt():
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    sealed = FernetSecretBox([old]).seal("whsec_abc")

    rotated = FernetSecretBox([new, old])

    assert rotated.open(sealed) == "whsec_abc"
    # What it seals now opens with the new key alone
    assert FernetSecretBox([new]).open(rotated.seal("whsec_def")) == "whsec_def"


def test_without_the_key_that_sealed_it_a_secret_does_not_open():
    sealed = FernetSecretBox([Fernet.generate_key().decode()]).seal("whsec_abc")

    with pytest.raises(RuntimeError, match="the key that encrypted it is missing"):
        FernetSecretBox([Fernet.generate_key().decode()]).open(sealed)


def test_local_falls_back_to_the_development_key():
    box = FernetSecretBox.from_config(_config("local"))

    assert box.keys == [DEVELOPMENT_KEY]


@pytest.mark.parametrize(
    ("keys", "message"),
    [
        ("", "SECRET_ENCRYPTION_KEYS or SECRET_ENCRYPTION_KEYS_FILE is required"),
        (DEVELOPMENT_KEY, "The development secret encryption key can't be used"),
        ("not a key", "is not a Fernet key"),
    ],
)
def test_outside_local_a_real_key_is_required(keys, message):
    with pytest.raises(RuntimeError, match=message):
        FernetSecretBox.from_config(_config(keys=keys))


def test_the_keys_can_come_from_a_file(tmp_path):
    first, second = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    path = tmp_path / "keys"
    path.write_text(f"{first}\n{second}\n")

    box = FernetSecretBox.from_config(_config(path=str(path)))

    assert box.keys == [first, second]


def test_the_variable_and_the_file_are_not_both_allowed(tmp_path):
    with pytest.raises(RuntimeError, match="not both"):
        FernetSecretBox.from_config(
            _config(keys=Fernet.generate_key().decode(), path=str(tmp_path / "keys"))
        )
