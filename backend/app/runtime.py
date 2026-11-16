import asyncio
import selectors
import sys
from collections.abc import Callable


def selector_loop_factory() -> Callable[[], asyncio.AbstractEventLoop] | None:
    """psycopg async needs a selector event loop; Windows defaults to Proactor."""
    if sys.platform == "win32":
        return lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
    return None
