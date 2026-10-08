class Entity:
    id: int | None

    def dict(self):
        return self.__dict__

    def require_id(self) -> int:
        """Return the id of a persisted entity; raise if it was never saved."""
        if self.id is None:
            raise RuntimeError(f"{type(self).__name__} has no id; it is not persisted")
        return self.id
