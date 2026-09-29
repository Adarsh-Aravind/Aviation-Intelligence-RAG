"""PostgreSQL connection pool (psycopg 3)."""

import logging

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)


def create_pool(database_url: str, min_size: int = 1, max_size: int = 5) -> ConnectionPool:
    """Create a small pool suited to a 4 GB host.

    ``prepare_threshold=None`` keeps us compatible with Supabase's transaction-mode pooler
    (which does not support prepared statements); it is harmless in session mode.
    """
    pool = ConnectionPool(
        conninfo=database_url,
        min_size=min_size,
        max_size=max_size,
        kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row},
        check=ConnectionPool.check_connection,
        max_idle=300,
        timeout=8,  # fail fast (-> 503) during an internet outage instead of hanging requests
        reconnect_timeout=120,  # give up a reconnect cycle quickly; the watchdog/requests start a new one
        open=False,
        name="rag-pool",
    )
    pool.open(wait=False)
    return pool
