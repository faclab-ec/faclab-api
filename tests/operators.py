from src.shared.app.platform import PlatformOperators


class FakePlatformOperators(PlatformOperators):
    """The platform's operators for unit tests: the user ids given"""

    def __init__(self, *user_ids: int):
        self.user_ids = set(user_ids)

    def is_operator(self, user_id: int) -> bool:
        return user_id in self.user_ids
