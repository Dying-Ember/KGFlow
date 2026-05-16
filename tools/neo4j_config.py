"""Neo4j connection configuration — from environment with hardcoded fallback."""

import os
from typing import Optional

NEO4J_URI: str = os.environ.get("KGFLOW_NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER: str = os.environ.get("KGFLOW_NEO4J_USER", "neo4j")
NEO4J_PASSWORD: Optional[str] = os.environ.get("KGFLOW_NEO4J_PASSWORD")

if not NEO4J_PASSWORD:
    NEO4J_PASSWORD = ""
