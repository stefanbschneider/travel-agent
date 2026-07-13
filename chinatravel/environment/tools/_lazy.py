"""Lazy-construction proxy for expensive tool singletons.

Several verifier/evaluator modules build Accommodations/Restaurants/Attractions/...
at module import time. Each of those constructors reads every city's CSV into a
pandas DataFrame, so importing a module that is never actually called (e.g. it
only supplies one function used elsewhere in the process) still pays that cost.
``LazyTool`` defers construction to first attribute access so import stays cheap;
callers should pair it with an ``lru_cache``-wrapped factory so repeated access
does not rebuild the underlying object.
"""


class LazyTool:
    """Transparently delegates attribute access to ``factory()``, called on first use."""

    __slots__ = ("_factory",)

    def __init__(self, factory):
        object.__setattr__(self, "_factory", factory)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_factory")(), name)
