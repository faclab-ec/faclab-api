"""Intentionally failing test to check that CI turns red (S1.1). Never merge."""


def test_ci_turns_red():
    assert False, "intentional failure"
