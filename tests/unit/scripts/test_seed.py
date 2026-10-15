import pytest

from scripts import seed


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_seed_refuses_to_run_outside_local(monkeypatch, mocker, environment):
    monkeypatch.setenv("ENVIRONMENT", environment)
    get_session = mocker.patch.object(seed, "get_session")

    with pytest.raises(SystemExit, match="ENVIRONMENT=local"):
        seed.main()

    get_session.assert_not_called()


def test_seed_runs_in_local(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "local")

    seed.ensure_local_environment()
