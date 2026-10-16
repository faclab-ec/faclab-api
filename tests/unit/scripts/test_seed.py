import pytest

from scripts import seed


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_seed_refuses_to_run_outside_local(monkeypatch, mocker, environment):
    monkeypatch.setenv("ENVIRONMENT", environment)
    provision_tenants = mocker.patch.object(seed, "provision_tenants")
    get_session_maker = mocker.patch.object(seed, "get_session_maker")

    with pytest.raises(SystemExit, match="ENVIRONMENT=local"):
        seed.main()

    provision_tenants.assert_not_called()
    get_session_maker.assert_not_called()


def test_seed_runs_in_local(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "local")

    seed.ensure_local_environment()
