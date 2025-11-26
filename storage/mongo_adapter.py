"""
MongoDB Adapter
===============

Read/write adapter for agent logs stored in MongoDB.
Supports per-agent isolation with clustered read access for evaluator.
"""

import os
from typing import List, Dict, Any, Optional
from pymongo import MongoClient
from datetime import datetime
from .schemas import MongoSchema


class MongoAdapter:
    """
    MongoDB adapter for agent logs and memories.
    
    Agents: Full read/write to their own database
    Evaluator: Read access across all agent databases (clustered)
    """
    
    def __init__(
        self,
        connection_string: Optional[str] = None,
        agent_id: Optional[str] = None,
        cluster_mode: bool = False
    ):
        """
        Initialize MongoDB adapter.
        
        Args:
            connection_string: MongoDB connection string. If None, uses MONGODB_URL env var.
            agent_id: Agent identifier (used for database name if not in connection string)
            cluster_mode: If True, enables read access to multiple agent databases
        """
        self.agent_id = agent_id or os.getenv("AGENT_ID", "agent1")
        self.cluster_mode = cluster_mode
        
        # Get connection string from env or parameter
        if connection_string:
            base_url = connection_string
        else:
            base_url = os.getenv("MONGODB_URL", "mongodb://admin:password@localhost:27017")
        
        # Process connection string based on mode
        if cluster_mode:
            # Cluster mode: extract base URL without database name
            # Parse URL: mongodb://[user:pass@]host:port[/db][?options]
            # Split by '://' to separate scheme from rest
            if '://' in base_url:
                scheme, rest = base_url.split('://', 1)
                # Split rest by '/' to separate host:port from db/options
                if '/' in rest:
                    host_part, path_part = rest.split('/', 1)
                    # Remove database name, keep only query params if present
                    if '?' in path_part:
                        # Has query params, keep them
                        query_params = '?' + path_part.split('?', 1)[1]
                        self.connection_string = f"{scheme}://{host_part}{query_params}"
                    else:
                        # No query params, just remove database name
                        self.connection_string = f"{scheme}://{host_part}"
                else:
                    # No database in URL
                    self.connection_string = base_url
            else:
                self.connection_string = base_url
        else:
            # Single agent mode: use agent-specific database
            db_name = f"{self.agent_id}db"
            if '/' in base_url and not base_url.endswith('/'):
                # Replace database name
                parts = base_url.rsplit('/', 1)
                query_params = ''
                if '?' in parts[1]:
                    db_part, query_params = parts[1].split('?', 1)
                    query_params = '?' + query_params
                else:
                    db_part = parts[1].split('?')[0]
                
                self.connection_string = f"{parts[0]}/{db_name}{query_params}"
            else:
                query_params = '?' + base_url.split('?')[1] if '?' in base_url else ''
                self.connection_string = f"{base_url.rstrip('/')}/{db_name}{query_params}"
        
        # Connect to MongoDB
        self.client = MongoClient(self.connection_string)
        
        # Extract database name for single agent mode
        if not cluster_mode:
            db_part = self.connection_string.split('/')[-1].split('?')[0]
            self.db_name = db_part if db_part else f"{self.agent_id}db"
            self.db = self.client[self.db_name]
            self._init_collections()
        else:
            # Cluster mode: will connect to multiple databases dynamically
            self.databases = {}
    
    def _init_collections(self):
        """Initialize collections and indexes for single agent database."""
        self.logs = self.db.agent_logs
        self.memories = self.db.agent_memories
        self.config = self.db.agent_config
        
        # Create indexes
        self.logs.create_index("agent_id")
        self.logs.create_index("created_at")
        self.logs.create_index("level")
        self.logs.create_index("task_id")
        
        self.memories.create_index("agent_id")
        self.memories.create_index("created_at")
        self.memories.create_index("memory_type")
        
        self.config.create_index("key", unique=True)
    
    def write_log(
        self,
        level: str,
        message: str,
        task_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None
    ) -> str:
        """
        Write log entry to MongoDB.
        
        Args:
            level: Log level (info, error, warning, debug)
            message: Log message
            task_id: Optional task identifier
            metadata: Optional additional metadata
            timestamp: Optional explicit timestamp (if None, uses current time)
            
        Returns:
            Log entry ID
        """
        if self.cluster_mode:
            raise ValueError("Cannot write in cluster mode. Use agent-specific adapter.")
        
        log_entry = MongoSchema.log_entry(
            level=level,
            message=message,
            agent_id=self.agent_id,
            task_id=task_id,
            metadata=metadata,
            timestamp=timestamp
        )
        result = self.logs.insert_one(log_entry)
        return str(result.inserted_id)
    
    def read_logs(
        self,
        agent_id: Optional[str] = None,
        level: Optional[Any] = None,
        task_id: Optional[str] = None,
        limit: int = 50,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Read logs from MongoDB.
        
        Args:
            agent_id: Agent identifier (only used in cluster mode)
            level: Filter by log level (can be string or MongoDB query dict like {"$ne": "debug"})
            task_id: Filter by task ID
            limit: Maximum number of results
            start_time: Filter logs after this time
            end_time: Filter logs before this time
            
        Returns:
            List of log entries
        """
        query = {}
        
        if agent_id and self.cluster_mode:
            # Cluster mode: connect to specific agent database
            db_name = f"{agent_id}db"
            if db_name not in self.databases:
                # Parse connection string to construct agent-specific URL
                # connection_string format: mongodb://user:pass@host:port[/dbname][?options]
                # We need to replace any existing database name with the agent's database
                if '?' in self.connection_string:
                    base_url, query_params = self.connection_string.split('?', 1)
                    # Remove any existing database name from base_url
                    # mongodb://user:pass@host:port/dbname -> mongodb://user:pass@host:port
                    if base_url.count('/') >= 3:
                        base_url = '/'.join(base_url.split('/')[:-1])
                    db_url = f"{base_url}/{db_name}?{query_params}"
                else:
                    # Remove any existing database name
                    base_url = self.connection_string
                    if base_url.count('/') >= 3:
                        base_url = '/'.join(base_url.split('/')[:-1])
                    db_url = f"{base_url}/{db_name}?authSource=admin"
                
                try:
                    client = MongoClient(db_url)
                    db = client[db_name]
                    
                    # Check if database exists by listing collections
                    # If the agent hasn't started yet, the database won't exist
                    collections = db.list_collection_names()
                    
                    self.databases[db_name] = {
                        "client": client,
                        "db": db,
                        "logs": db.agent_logs,
                        "initialized": len(collections) > 0
                    }
                except Exception as e:
                    # Return empty list instead of raising error if agent database doesn't exist yet
                    # This is expected when agents haven't started or haven't written any logs
                    return []
            
            # Return empty list if database exists but isn't initialized (no collections)
            if db_name in self.databases and not self.databases[db_name].get("initialized", False):
                return []
            
            if db_name not in self.databases or "logs" not in self.databases[db_name]:
                # Database connection failed or logs collection not found
                return []
            
            logs_collection = self.databases[db_name]["logs"]
        else:
            if not self.cluster_mode and agent_id and agent_id != self.agent_id:
                raise ValueError(f"Cannot read logs from different agent in single mode. Use cluster_mode=True.")
            logs_collection = self.logs
        
        if agent_id and self.cluster_mode:
            query["agent_id"] = agent_id
        elif not self.cluster_mode:
            query["agent_id"] = self.agent_id
        
        if level is not None:
            # Support both string and dict (for MongoDB operators like $ne)
            query["level"] = level
        
        if task_id:
            query["task_id"] = task_id
        
        if start_time:
            query["created_at"] = {"$gte": start_time}
        
        if end_time:
            if "created_at" in query:
                query["created_at"]["$lte"] = end_time
            else:
                query["created_at"] = {"$lte": end_time}
        
        cursor = logs_collection.find(query).sort("created_at", -1).limit(limit)
        return list(cursor)
    
    def write_memory(
        self,
        content: str,
        memory_type: str = "general",
        task_id: Optional[str] = None
    ) -> str:
        """
        Write memory entry to MongoDB.
        
        Args:
            content: Memory content
            memory_type: Type of memory
            task_id: Optional task identifier
            
        Returns:
            Memory entry ID
        """
        if self.cluster_mode:
            raise ValueError("Cannot write in cluster mode. Use agent-specific adapter.")
        
        memory_entry = MongoSchema.memory_entry(
            content=content,
            agent_id=self.agent_id,
            memory_type=memory_type,
            task_id=task_id
        )
        result = self.memories.insert_one(memory_entry)
        return str(result.inserted_id)
    
    def read_memories(
        self,
        agent_id: Optional[str] = None,
        memory_type: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Read memories from MongoDB.
        
        Args:
            agent_id: Agent identifier (only used in cluster mode)
            memory_type: Filter by memory type
            limit: Maximum number of results
            
        Returns:
            List of memory entries
        """
        query = {}
        
        if agent_id and self.cluster_mode:
            db_name = f"{agent_id}db"
            if db_name not in self.databases:
                # Parse connection string to construct agent-specific URL
                if '?' in self.connection_string:
                    base_url, query_params = self.connection_string.split('?', 1)
                    db_url = f"{base_url}/{db_name}?{query_params}"
                else:
                    db_url = f"{self.connection_string}/{db_name}?authSource=admin"
                
                try:
                    client = MongoClient(db_url)
                    db = client[db_name]
                    
                    # Check if database exists by listing collections
                    collections = db.list_collection_names()
                    
                    self.databases[db_name] = {
                        "client": client,
                        "db": db,
                        "memories": db.agent_memories,
                        "initialized": len(collections) > 0
                    }
                except Exception as e:
                    # Return empty list if agent database doesn't exist yet
                    return []
            
            # Return empty list if database exists but isn't initialized
            if db_name in self.databases and not self.databases[db_name].get("initialized", False):
                return []
            
            if db_name not in self.databases or "memories" not in self.databases[db_name]:
                return []
            
            memories_collection = self.databases[db_name]["memories"]
        else:
            if not self.cluster_mode and agent_id and agent_id != self.agent_id:
                raise ValueError(f"Cannot read memories from different agent in single mode.")
            memories_collection = self.memories
        
        if agent_id and self.cluster_mode:
            query["agent_id"] = agent_id
        elif not self.cluster_mode:
            query["agent_id"] = self.agent_id
        
        if memory_type:
            query["memory_type"] = memory_type
        
        cursor = memories_collection.find(query).sort("created_at", -1).limit(limit)
        return list(cursor)
    
    def read_all_agent_logs(
        self,
        agent_ids: List[str],
        level: Optional[str] = None,
        limit_per_agent: int = 50
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Read logs from multiple agents (evaluator use case).
        
        Args:
            agent_ids: List of agent identifiers
            level: Filter by log level
            limit_per_agent: Maximum results per agent
            
        Returns:
            Dictionary mapping agent_id to list of logs
        """
        if not self.cluster_mode:
            raise ValueError("Cluster mode required for reading all agent logs.")
        
        results = {}
        for agent_id in agent_ids:
            results[agent_id] = self.read_logs(
                agent_id=agent_id,
                level=level,
                limit=limit_per_agent
            )
        
        return results
    
    def get_screenshots(
        self,
        agent_id: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get screenshots from MongoDB.
        
        Args:
            agent_id: Agent identifier (required if not cluster mode)
            limit: Maximum number of screenshots to return
            
        Returns:
            List of screenshot documents
        """
        if self.cluster_mode:
            if not agent_id:
                raise ValueError("agent_id required in cluster mode")
            db_name = f"{agent_id}db"
            if db_name not in self.databases:
                # Parse connection string to construct agent-specific URL
                if '?' in self.connection_string:
                    base_url, query_params = self.connection_string.split('?', 1)
                    db_url = f"{base_url}/{db_name}?{query_params}"
                else:
                    db_url = f"{self.connection_string}/{db_name}?authSource=admin"
                
                try:
                    client = MongoClient(db_url)
                    db = client[db_name]
                    
                    # Check if database exists by listing collections
                    collections = db.list_collection_names()
                    
                    self.databases[db_name] = {
                        "client": client,
                        "db": db,
                        "screenshots": db.screenshots,
                        "initialized": len(collections) > 0
                    }
                except Exception as e:
                    # Return empty list if agent database doesn't exist yet
                    return []
            
            # Return empty list if database exists but isn't initialized
            if db_name in self.databases and not self.databases[db_name].get("initialized", False):
                return []
            
            if db_name not in self.databases or "screenshots" not in self.databases[db_name]:
                return []
            
            screenshots_collection = self.databases[db_name]["screenshots"]
        else:
            if agent_id and agent_id != self.agent_id:
                raise ValueError(f"Cannot read screenshots from different agent in single mode.")
            screenshots_collection = self.screenshots
        
        query = {}
        if agent_id and self.cluster_mode:
            query["agent_id"] = agent_id
        elif not self.cluster_mode:
            query["agent_id"] = self.agent_id
        
        cursor = screenshots_collection.find(query).sort("uploaded_at", -1).limit(limit)
        return list(cursor)
    
    def fetch_task_logs(
        self,
        agent_id: str,
        task_id: str
    ) -> List[Dict[str, Any]]:
        """
        Fetch all logs for a specific task.
        
        Args:
            agent_id: Agent identifier
            task_id: Task identifier (can be string or int)
            
        Returns:
            List of log entries for the task
        """
        # Try both string and integer task_id since MongoDB might store it as either
        try:
            task_id_int = int(task_id)
        except (ValueError, TypeError):
            task_id_int = None
        
        # Try string first
        logs = self.read_logs(
            agent_id=agent_id,
            task_id=task_id,
            limit=1000
        )
        
        # If no logs found and we can convert to int, try int
        if not logs and task_id_int is not None:
            logs = self.read_logs(
                agent_id=agent_id,
                task_id=task_id_int,
                limit=1000
            )
        
        return logs
    
    def fetch_task_logs_until(
        self,
        agent_id: str,
        task_id: str,
        cutoff_time: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch logs for a task up to a specific time.
        
        Args:
            agent_id: Agent identifier
            task_id: Task identifier
            cutoff_time: Only return logs before this time
            
        Returns:
            List of log entries for the task up to cutoff_time
        """
        return self.read_logs(
            agent_id=agent_id,
            task_id=task_id,
            end_time=cutoff_time,
            limit=1000
        )
    
    def compute_basic_metrics(
        self,
        logs: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Compute basic metrics from log entries.
        
        Args:
            logs: List of log entries
            
        Returns:
            Dictionary of computed metrics
        """
        if not logs:
            return {
                "error_count": 0,
                "retry_count": 0,
                "total_api_calls": 0,
                "human_or_agent_requests": 0,
                "completion_time_s": 0.0
            }
        
        # Sort logs by timestamp
        sorted_logs = sorted(
            logs,
            key=lambda x: x.get("created_at") or x.get("timestamp") or datetime.min
        )
        
        error_count = sum(1 for log in logs if log.get("level") == "error")
        retry_count = sum(1 for log in logs if "retry" in str(log.get("message", "")).lower())
        
        # Count API calls from log messages
        api_call_patterns = ["api", "openai", "gpt", "completion", "request"]
        total_api_calls = sum(
            1 for log in logs
            if any(pattern in str(log.get("message", "")).lower() for pattern in api_call_patterns)
        )
        
        # Count dependency requests
        dependency_patterns = ["human", "agent", "help", "assistance", "request"]
        human_or_agent_requests = sum(
            1 for log in logs
            if any(pattern in str(log.get("message", "")).lower() for pattern in dependency_patterns)
        )
        
        # Calculate completion time
        completion_time_s = 0.0
        if sorted_logs:
            start_time = sorted_logs[0].get("created_at") or sorted_logs[0].get("timestamp")
            end_time = sorted_logs[-1].get("created_at") or sorted_logs[-1].get("timestamp")
            
            if start_time and end_time:
                if isinstance(start_time, str):
                    try:
                        start_time = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                    except:
                        start_time = None
                if isinstance(end_time, str):
                    try:
                        end_time = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                    except:
                        end_time = None
                
                if start_time and end_time:
                    delta = end_time - start_time
                    completion_time_s = delta.total_seconds()
        
        return {
            "error_count": error_count,
            "retry_count": retry_count,
            "total_api_calls": total_api_calls,
            "human_or_agent_requests": human_or_agent_requests,
            "completion_time_s": completion_time_s
        }
    
    def get_most_recent_task_id(
        self,
        agent_id: str
    ) -> Optional[str]:
        """
        Get the most recent task ID for an agent from logs.
        
        Args:
            agent_id: Agent identifier
            
        Returns:
            Most recent task ID or None if no logs found
        """
        if not self.cluster_mode:
            raise ValueError("Cluster mode required to get task ID from different agent.")
        
        # Get recent logs for the agent, sorted by created_at descending
        logs = self.read_logs(agent_id=agent_id, limit=100)
        
        if not logs:
            return None
        
        # Find the most recent task_id (logs are already sorted by created_at desc)
        for log in logs:
            task_id = log.get("task_id")
            # Handle both None and empty values, and convert to string
            if task_id is not None and task_id != "":
                # Convert to string, handling both int and string types
                return str(task_id)
        
        return None
    
    def close(self):
        """Close MongoDB connections."""
        if self.cluster_mode:
            for db_info in self.databases.values():
                db_info["client"].close()
        self.client.close()

