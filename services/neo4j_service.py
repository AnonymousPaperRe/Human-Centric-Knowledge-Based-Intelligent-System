"""
Neo4j service — uses the raw neo4j Python driver (a module-level singleton)
instead of neomodel's db.cypher_query(), which inherits threading.local and
loses its connection in Streamlit's worker threads.
"""
import threading
from urllib.parse import urlparse

from neo4j import GraphDatabase
from config import NEO4J_BOLT

# Module-level driver shared across all threads
_driver = None
_lock = threading.Lock()


def connect():
    """Create (or recreate) the module-level Neo4j driver."""
    global _driver
    parsed = urlparse(NEO4J_BOLT)
    uri = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
    auth = (parsed.username, parsed.password)
    with _lock:
        _driver = GraphDatabase.driver(uri, auth=auth)


def _get_driver():
    if _driver is None:
        connect()
    return _driver


def _serialize(val):
    """Recursively convert neo4j graph types to plain Python objects."""
    # Import here to avoid errors if the type changed across driver versions
    try:
        from neo4j.graph import Node, Relationship
        if isinstance(val, Node):
            return dict(val.items())
        if isinstance(val, Relationship):
            return {"_rel_type": val.type, **dict(val.items())}
    except ImportError:
        pass
    if isinstance(val, list):
        return [_serialize(v) for v in val]
    if isinstance(val, dict):
        return {k: _serialize(v) for k, v in val.items()}
    # Fallback for objects that expose .items() (e.g. older driver versions)
    if hasattr(val, "_properties"):
        return dict(val._properties)
    return val


def run_cypher(query: str, params: dict = None) -> list:
    """Execute a Cypher query and return results as a list of dicts."""
    if params is None:
        params = {}
    driver = _get_driver()
    with driver.session() as session:
        result = session.run(query, params)
        return [
            {key: _serialize(record[key]) for key in record.keys()}
            for record in result
        ]


def safe_run(query: str, params: dict = None):
    """Execute Cypher with exception handling. Returns {ok, data, error}."""
    try:
        data = run_cypher(query, params or {})
        return {"ok": True, "data": data, "error": None}
    except Exception as exc:
        return {"ok": False, "data": [], "error": str(exc)}
