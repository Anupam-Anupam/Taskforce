"""
Storage Schemas
===============

Schema definitions for MongoDB, PostgreSQL, and MinIO metadata.
"""

from typing import Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum


# MongoDB Collections
class MongoSchema:
    """
    MongoDB document schemas for agent logs.
    
    Collections:
    - agent_logs: Activity and error logs
    - agent_memories: Agent memory window
    - agent_config: Configuration settings
    """
    
    # Log entry schema
    @staticmethod
    def log_entry(
        level: str,
        message: str,
        agent_id: str,
        task_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Log entry document structure.
        
        Args:
            level: Log level (info, error, warning, debug)
            message: Log message
            agent_id: Agent identifier
            task_id: Optional task identifier
            metadata: Optional additional metadata
            timestamp: Optional explicit timestamp (if None, uses current time)
            
        Returns:
            Dictionary matching MongoDB document schema
        """
        # Use provided timestamp or current time
        # This allows callers to set accurate timestamps for events that happened in the past
        entry_time = timestamp if timestamp is not None else datetime.utcnow()
        
        return {
            "level": level,
            "message": message,
            "agent_id": agent_id,
            "task_id": task_id,
            "metadata": metadata or {},
            "created_at": entry_time,
            "timestamp": entry_time  # Also store as 'timestamp' for backward compatibility
        }
    
    # Memory entry schema
    @staticmethod
    def memory_entry(
        content: str,
        agent_id: str,
        memory_type: str = "general",
        task_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Memory entry document structure.
        
        Args:
            content: Memory content
            agent_id: Agent identifier
            memory_type: Type of memory (general, task_result, observation)
            task_id: Optional task identifier
            
        Returns:
            Dictionary matching MongoDB document schema
        """
        return {
            "content": content,
            "agent_id": agent_id,
            "memory_type": memory_type,
            "task_id": task_id,
            "created_at": datetime.utcnow()
        }


# PostgreSQL Tables
class PostgresSchema:
    """
    PostgreSQL table schemas for task progress and metadata.
    
    Tables:
    - tasks: Task assignments and progress
    - task_progress: Task progress updates
    - evaluations: Evaluation scores and reports
    - agents: Agent metadata
    """
    
    # Task status enum
    class TaskStatus(Enum):
        PENDING = "pending"
        IN_PROGRESS = "in_progress"
        COMPLETED = "completed"
        FAILED = "failed"
        CANCELLED = "cancelled"
    
    @staticmethod
    def task_record(
        agent_id: str,
        title: str,
        description: str,
        status: str = "pending",
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Task record structure.
        
        Args:
            agent_id: Agent identifier
            title: Task title
            description: Task description
            status: Task status
            metadata: Optional task metadata
            
        Returns:
            Dictionary for database insertion
        """
        return {
            "agent_id": agent_id,
            "title": title,
            "description": description,
            "status": status,
            "metadata": metadata or {},
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
    
    @staticmethod
    def progress_update(
        task_id: int,
        agent_id: str,
        progress_percent: float,
        message: str,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Progress update record structure.
        
        Args:
            task_id: Task identifier
            agent_id: Agent identifier
            progress_percent: Progress percentage (0-100)
            message: Progress message
            data: Optional progress data
            
        Returns:
            Dictionary for database insertion
        """
        return {
            "task_id": task_id,
            "agent_id": agent_id,
            "progress_percent": progress_percent,
            "message": message,
            "data": data or {},
            "timestamp": datetime.utcnow()
        }
    
    @staticmethod
    def evaluation_record(
        task_id: int,
        agent_id: str,
        score: float,
        report: str,
        metrics: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Evaluation record structure.
        
        Args:
            task_id: Task identifier
            agent_id: Agent identifier
            score: Evaluation score
            report: Evaluation report
            metrics: Optional evaluation metrics
            
        Returns:
            Dictionary for database insertion
        """
        return {
            "task_id": task_id,
            "agent_id": agent_id,
            "score": score,
            "report": report,
            "metrics": metrics or {},
            "created_at": datetime.utcnow()
        }


# MinIO Metadata
class MinIOSchema:
    """
    MinIO object metadata schemas.
    
    Metadata stored in PostgreSQL for efficient querying.
    Binary files stored in MinIO buckets.
    """
    
    @staticmethod
    def screenshot_metadata(
        agent_id: str,
        task_id: Optional[int],
        object_path: str,
        content_type: str = "image/png",
        size_bytes: int = 0,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Screenshot metadata record structure.
        
        Args:
            agent_id: Agent identifier
            task_id: Optional task identifier
            object_path: MinIO object path
            content_type: MIME type
            size_bytes: File size in bytes
            metadata: Optional additional metadata
            
        Returns:
            Dictionary for database insertion
        """
        return {
            "agent_id": agent_id,
            "task_id": task_id,
            "object_path": object_path,
            "bucket": "screenshots",
            "content_type": content_type,
            "size_bytes": size_bytes,
            "metadata": metadata or {},
            "uploaded_at": datetime.utcnow()
        }
    
    @staticmethod
    def binary_file_metadata(
        agent_id: str,
        task_id: Optional[int],
        object_path: str,
        bucket: str,
        content_type: str,
        size_bytes: int = 0,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generic binary file metadata record structure.
        
        Args:
            agent_id: Agent identifier
            task_id: Optional task identifier
            object_path: MinIO object path
            bucket: MinIO bucket name
            content_type: MIME type
            size_bytes: File size in bytes
            metadata: Optional additional metadata
            
        Returns:
            Dictionary for database insertion
        """
        return {
            "agent_id": agent_id,
            "task_id": task_id,
            "object_path": object_path,
            "bucket": bucket,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "metadata": metadata or {},
            "uploaded_at": datetime.utcnow()
        }

