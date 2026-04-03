import os

NEO4J_BOLT = os.getenv("NEO4J_BOLT", "bolt://neo4j:12345678@localhost:7687")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
