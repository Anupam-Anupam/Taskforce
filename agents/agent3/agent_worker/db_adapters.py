# Database adapters: PostgreSQL and MongoDB clients for task polling and logging
"""Database adapters for PostgreSQL and MongoDB."""

import psycopg2
import psycopg2.pool
from psycopg2.extras import RealDictCursor
from pymongo import MongoClient
from typing import Optional, Dict, Any, List
from datetime import datetime
import traceback
import json


class PostgresClient:
    """PostgreSQL client for task polling and progress updates."""
    
    def __init__(self, dsn: str):
        """
        Initialize PostgreSQL client.
        
        Args:
            dsn: PostgreSQL connection string (psycopg2 DSN format)
        """
        self.dsn = dsn
        self.conn = None
        self._connect()
    
    def _connect(self):
        """Establish connection to PostgreSQL."""
        try:
            self.conn = psycopg2.connect(self.dsn)
            self.conn.autocommit = False
        except Exception as e:
            error_msg = str(e)
            # Provide helpful error message for common hostname resolution issues
            if "could not translate host name" in error_msg.lower() or "name or service not known" in error_msg.lower():
                if "postgres" in self.dsn:
                    raise RuntimeError(
                        f"Failed to connect to PostgreSQL: {error_msg}\n"
                        f"Hint: The hostname 'postgres' only works inside Docker networks. "
                        f"For local development, use 'localhost:5433' instead. "
                        f"Example: postgresql://hub:hubpassword@localhost:5433/hub"
                    )
            raise RuntimeError(f"Failed to connect to PostgreSQL: {e}")
    
    def _ensure_connection(self):
        """Ensure connection is alive, reconnect if needed."""
        try:
            if self.conn and self.conn.closed == 0:
                # Check if transaction is in error state and rollback if needed
                try:
                    # Try to rollback any aborted transaction
                    self.conn.rollback()
                except:
                    pass
                
                # Test connection
                with self.conn.cursor() as cur:
                    cur.execute("SELECT 1")
                return
        except:
            pass
        
        # Reconnect
        try:
            if self.conn:
                self.conn.close()
        except:
            pass
        self._connect()
    
    def get_task_by_id(self, task_id: int) -> Optional[Dict[str, Any]]:
        """Get a specific task by ID."""
        self._ensure_connection()
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, agent_id, title, description, status, 
                           metadata, created_at, updated_at
                    FROM tasks
                    WHERE id = %s
                """, (task_id,))
                row = cur.fetchone()
                if row:
                    return dict(row)
                return None
        except Exception as e:
            print(f"Warning: Failed to get task {task_id}: {e}")
            return None

    def get_tasks_by_group_id(self, group_id: str) -> List[Dict[str, Any]]:
        """Get all tasks belonging to a specific group ID (collaborative tasks)."""
        self._ensure_connection()
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Query tasks where metadata->>'group_id' matches
                cur.execute("""
                    SELECT id, agent_id, status, metadata
                    FROM tasks
                    WHERE metadata->>'group_id' = %s
                """, (group_id,))
                return [dict(row) for row in cur.fetchall()]
        except Exception as e:
            print(f"Warning: Failed to get group tasks: {e}")
            return []

    def get_current_task(self, agent_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get the most recent pending task from the tasks table.
        Optionally filter by agent_id so workers only pull their own tasks.
        
        Returns:
            Task record as dictionary or None if no task found
        """
        self._ensure_connection()
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Select most recent pending task by ID (greatest ID = most recent)
                query = """
                    SELECT id, agent_id, title, description, status, 
                           metadata, created_at, updated_at
                    FROM tasks
                    WHERE status = 'pending'
                """
                params = []
                if agent_id:
                    query += " AND agent_id = %s"
                    params.append(agent_id)
                
                query += " ORDER BY id DESC LIMIT 1"
                cur.execute(query, tuple(params))
                row = cur.fetchone()
                if row:
                    return dict(row)
                return None
        except Exception as e:
            print(f"Warning: Failed to get current task: {e}")
            return None
    
    def get_task_progress_max_percent(self, task_id: int) -> int:
        """
        Get maximum progress percent for a task from task_progress table.
        
        Args:
            task_id: Task identifier
            
        Returns:
            Maximum progress percent (0-100)
        """
        self._ensure_connection()
        try:
            with self.conn.cursor() as cur:
                # Try progress_percent column first (from schema)
                cur.execute("""
                    SELECT COALESCE(MAX(progress_percent), 0) as max_percent
                    FROM task_progress
                    WHERE task_id = %s
                """, (task_id,))
                row = cur.fetchone()
                if row and row[0] is not None:
                    return int(row[0])
                
                # Fallback: try 'percent' column if progress_percent doesn't exist
                try:
                    cur.execute("""
                        SELECT COALESCE(MAX(percent), 0) as max_percent
                        FROM task_progress
                        WHERE task_id = %s
                    """, (task_id,))
                    row = cur.fetchone()
                    if row and row[0] is not None:
                        return int(row[0])
                except:
                    pass
                
                return 0
        except Exception as e:
            # If table/column doesn't exist, return 0
            return 0
    
    def insert_progress(
        self, 
        task_id: int, 
        agent_id: str, 
        percent: Optional[float], 
        message: str
    ) -> None:
        """
        Insert a progress update into task_progress table.
        
        Args:
            task_id: Task identifier
            agent_id: Agent identifier
            percent: Progress percent (0-100) or None
            message: Progress message
        """
        self._ensure_connection()
        
        # Try progress_percent column first (from schema)
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO task_progress (task_id, agent_id, progress_percent, message, timestamp)
                    VALUES (%s, %s, %s, %s, %s)
                """, (task_id, agent_id, percent, message, datetime.utcnow()))
                self.conn.commit()
                return
        except Exception as e:
            # Rollback before trying next method
            try:
                self.conn.rollback()
            except:
                pass
        
        # Fallback: try 'percent' column
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO task_progress (task_id, agent_id, percent, message, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                """, (task_id, agent_id, percent, message, datetime.utcnow()))
                self.conn.commit()
                return
        except Exception as e:
            # Rollback before trying next method
            try:
                self.conn.rollback()
            except:
                pass
        
        # Final fallback: try minimal insert
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO task_progress (task_id, agent_id, message, timestamp)
                    VALUES (%s, %s, %s, %s)
                """, (task_id, agent_id, message, datetime.utcnow()))
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            # Don't raise error - progress updates are optional
            pass
    
    def update_task_status(
        self,
        task_id: int,
        status: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Update task status in tasks table.
        
        Args:
            task_id: Task identifier
            status: New status (e.g., "completed", "failed", "in_progress")
            metadata: Optional metadata to merge into existing metadata
        """
        self._ensure_connection()
        
        # Explicitly rollback any aborted transaction before starting
        try:
            self.conn.rollback()
        except:
            pass
        
        try:
            with self.conn.cursor() as cur:
                if metadata:
                    # Update status and merge metadata
                    cur.execute("""
                        UPDATE tasks 
                        SET status = %s,
                            metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                            updated_at = %s
                        WHERE id = %s
                    """, (status, json.dumps(metadata), datetime.utcnow(), task_id))
                else:
                    # Just update status
                    cur.execute("""
                        UPDATE tasks 
                        SET status = %s,
                            updated_at = %s
                        WHERE id = %s
                    """, (status, datetime.utcnow(), task_id))
                
                if cur.rowcount > 0:
                    self.conn.commit()
                else:
                    self.conn.rollback()
        except Exception as e:
            self.conn.rollback()
            # Don't raise error - updating status is optional
            pass
    
    def update_task_response(
        self, 
        task_id: int, 
        agent_id: str, 
        response_text: str
    ) -> None:
        """
        Update tasks table with agent's final response.
        
        Args:
            task_id: Task identifier
            agent_id: Agent identifier
            response_text: Final response text
        """
        self._ensure_connection()
        
        # Explicitly rollback any aborted transaction before starting
        try:
            self.conn.rollback()
        except:
            pass
        
        # Update metadata JSONB column (which exists in the schema)
        # Store response in metadata since there's no dedicated response column
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    UPDATE tasks 
                    SET metadata = COALESCE(metadata, '{}'::jsonb) || 
                                   jsonb_build_object('response', %s, 'last_agent', %s, 'response_updated_at', %s),
                        updated_at = %s
                    WHERE id = %s
                """, (response_text, agent_id, datetime.utcnow().isoformat(), datetime.utcnow(), task_id))
                if cur.rowcount > 0:
                    self.conn.commit()
                    return
                else:
                    self.conn.rollback()
        except Exception as e:
            # If metadata update fails, just update updated_at
            try:
                self.conn.rollback()
            except:
                pass
        
        # Fallback: just update updated_at
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    UPDATE tasks 
                    SET updated_at = %s
                    WHERE id = %s
                """, (datetime.utcnow(), task_id))
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            # Don't raise error - updating response is optional
            pass
    
    def close(self):
        """Close PostgreSQL connection."""
        if self.conn:
            try:
                self.conn.close()
            except:
                pass


class MongoClientWrapper:
    """MongoDB client wrapper for agent logs."""
    
    def __init__(self, mongo_uri: str, agent_id: str):
        """
        Initialize MongoDB client.
        
        Args:
            mongo_uri: MongoDB connection string
            agent_id: Agent identifier (used for database name)
        """
        self.mongo_uri = mongo_uri
        self.agent_id = agent_id
        
        # Determine database name
        # If URI contains a database, use it; otherwise use agent_logs_db
        if '/' in mongo_uri and not mongo_uri.endswith('/'):
            parts = mongo_uri.rsplit('/', 1)
            if '?' in parts[1]:
                # Has query params, extract db name
                db_part = parts[1].split('?')[0]
                if db_part:
                    self.db_name = db_part
                else:
                    self.db_name = "agent_logs_db"
            else:
                self.db_name = parts[1] if parts[1] else "agent_logs_db"
        else:
            self.db_name = "agent_logs_db"
        
        # Connect to MongoDB
        try:
            self.client = MongoClient(mongo_uri)
            self.db = self.client[self.db_name]
            self.logs = self.db.agent_logs
            
            # Create indexes
            self.logs.create_index("task_id")
            self.logs.create_index("level")
            self.logs.create_index("timestamp")
        except Exception as e:
            raise RuntimeError(f"Failed to connect to MongoDB: {e}")
    
    def write_log(
        self, 
        task_id: Optional[int], 
        level: str, 
        message: str, 
        meta: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None
    ) -> None:
        """
        Write a log entry to MongoDB agent_logs collection.
        
        Args:
            task_id: Optional task identifier
            level: Log level (info, error, warning, debug)
            message: Log message
            meta: Optional metadata dictionary
        """
        try:
            ts = timestamp or datetime.utcnow()
            log_doc = {
                "agent_id": self.agent_id,
                "task_id": task_id,
                "level": level,
                "message": message,
                "metadata": meta or {},
                "timestamp": ts,
                "created_at": ts
            }
            self.logs.insert_one(log_doc)
        except Exception as e:
            # Log to console if MongoDB write fails
            print(f"Warning: Failed to write log to MongoDB: {e}")
    
    def close(self):
        """Close MongoDB connection."""
        if self.client:
            try:
                self.client.close()
            except:
                pass

