from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wireup import AsyncContainer

# Global wireup container instance (initialized in main.py)
wireup_container: "AsyncContainer | None" = None
