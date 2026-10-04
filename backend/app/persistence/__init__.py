"""PostgreSQL implementations of the operational stores (``STORAGE_BACKEND=postgres``).

Each class keeps the public interface of its in-memory counterpart, so routes,
the agent graph and the tool gateway are unaware of which backend is active.
"""
