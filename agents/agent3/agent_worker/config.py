# Configuration module: reads environment variables and exposes Config dataclass
"""Configuration module for agent worker."""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    """Agent worker configuration from environment variables."""
    
    # PostgreSQL
    postgres_dsn: str
    
    # MongoDB
    mongo_uri: str
    
    # Agent
    agent_id: str
    
    # Worker settings
    poll_interval_seconds: int
    run_task_timeout_seconds: Optional[int]
    
    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        # PostgreSQL - support both POSTGRES_URL (existing convention) and POSTGRES_DSN
        postgres_dsn = os.getenv("POSTGRES_URL") or os.getenv("POSTGRES_DSN")
        if not postgres_dsn:
            raise ValueError("POSTGRES_URL or POSTGRES_DSN environment variable is required")
        
        # MongoDB - support both MONGODB_URL (existing convention) and MONGO_URI
        mongo_uri = os.getenv("MONGODB_URL") or os.getenv("MONGO_URI")
        if not mongo_uri:
            raise ValueError("MONGODB_URL or MONGO_URI environment variable is required")
        
        # Agent ID
        agent_id = os.getenv("AGENT_ID")
        if not agent_id:
            raise ValueError("AGENT_ID environment variable is required")
        
        # Worker settings with defaults
        poll_interval_seconds = int(os.getenv("POLL_INTERVAL_SECONDS", "5"))
        
        timeout_val = os.getenv("RUN_TASK_TIMEOUT_SECONDS")
        run_task_timeout_seconds = int(timeout_val) if timeout_val else None
        
        return cls(
            postgres_dsn=postgres_dsn,
            mongo_uri=mongo_uri,
            agent_id=agent_id,
            poll_interval_seconds=poll_interval_seconds,
            run_task_timeout_seconds=run_task_timeout_seconds
        )

