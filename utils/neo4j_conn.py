from typing import Any, Dict, List
import neo4j
from neo4j import GraphDatabase
from neo4j.exceptions import CypherSyntaxError

class Neo4jGraph:
    """Neo4j wrapper for graph operations."""
    
    def __init__(self, uri, user, password):
        self._driver = GraphDatabase.driver(uri, auth=(user, password))
    
    def close(self):
        """Closes the Neo4j connection."""
        if self._driver is not None:
            self._driver.close()
    
    def query(self, cypher_query: str, params=None):
        """Query Neo4j database."""
        with self._driver.session() as session:  # Do not specify database
            try:
                data = session.run(cypher_query, params)
                return [r.data() for r in data]
            except CypherSyntaxError as e:
                raise ValueError(f"Cypher statement is not valid: {e}")
        
        
    
        
    
