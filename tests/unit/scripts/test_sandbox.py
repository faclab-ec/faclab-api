import stat

import pytest

from scripts import sandbox

ARGS = [
    "--ruc",
    "0999999980001",
    "--legal-name",
    "Tienda Demo (sandbox)",
    "--admin-username",
    "tienda-demo",
    "--admin-email",
    "dev@tienda.example",
]


@pytest.mark.parametrize(
    ("environment", "integration_environment"),
    [
        ("production", None),
        ("production", "sandbox"),
        ("staging", "production"),
        ("local", "production"),
    ],
)
def test_it_refuses_outside_the_sandbox_deployment(
    monkeypatch, mocker, environment, integration_environment
):
    monkeypatch.setenv("ENVIRONMENT", environment)
    if integration_environment:
        monkeypatch.setenv("INTEGRATION_ENVIRONMENT", integration_environment)
    else:
        monkeypatch.delenv("INTEGRATION_ENVIRONMENT", raising=False)
    provision = mocker.patch.object(sandbox, "provision")

    with pytest.raises(SystemExit, match="INTEGRATION_ENVIRONMENT=sandbox"):
        sandbox.main(ARGS)

    provision.assert_not_called()


@pytest.mark.parametrize("environment", ["local", "staging"])
def test_it_runs_in_a_sandbox_deployment(monkeypatch, environment):
    monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.setenv("INTEGRATION_ENVIRONMENT", "sandbox")

    sandbox.ensure_sandbox_deployment()


def test_a_credentials_file_needs_a_client(monkeypatch, mocker, tmp_path):
    monkeypatch.setenv("ENVIRONMENT", "local")
    provision = mocker.patch.object(sandbox, "provision")

    code = sandbox.main([*ARGS, "--credentials-file", str(tmp_path / "c.env")])

    assert code == 2
    provision.assert_not_called()


def test_the_credentials_file_is_only_for_its_owner(tmp_path):
    path = tmp_path / "sandbox.env"
    path.write_text("old")
    path.chmod(0o644)

    sandbox.write_credentials(
        path, {"client_id": "fl_test_000000000001", "client_secret": "s3cr3t"}
    )

    assert path.read_text() == (
        "FACLAB_CLIENT_ID=fl_test_000000000001\nFACLAB_CLIENT_SECRET=s3cr3t\n"
    )
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_the_reset_clears_what_the_api_leaves_before_the_seed_order():
    order = sandbox.SANDBOX_TRUNCATE_ORDER
    first_seed_table = order.index(sandbox.seed.TRUNCATE_ORDER[0])
    api_tables = {"credit_notes", "invoice_discrepancies", "webhook_stock_changes"}
    assert {m.__tablename__ for m in order[:first_seed_table]} == api_tables
