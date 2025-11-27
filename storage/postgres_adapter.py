"""
PostgreSQL Adapter
==================

Adapter for task progress and metadata in PostgreSQL.
Agents: Partial write (progress + status)
Evaluator: Full read + write (scores & reports)
"""

import os
from typing import List, Dict, Any, Optional
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, JSON, ForeignKey, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime
from .schemas import PostgresSchema


Base = declarative_base()


# SQLAlchemy Models
class Task(Base):
    """Task table schema."""
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String, index=True, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text)
    status = Column(String, index=True, default="pending")
    task_metadata = Column("metadata", JSONB)  # Column name is "metadata" but attribute is task_metadata
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_agent_status', 'agent_id', 'status'),
    )


class TaskProgress(Base):
    """Task progress updates table schema."""
    __tablename__ = "task_progress"
    
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), index=True, nullable=False)
    agent_id = Column(String, index=True, nullable=False)
    progress_percent = Column(Float, default=0.0)
    message = Column(Text)
    data = Column(JSONB)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    
    __table_args__ = (
        Index('idx_task_timestamp', 'task_id', 'timestamp'),
    )


class Evaluation(Base):
    """Evaluation scores and reports table schema."""
    __tablename__ = "evaluations"
    
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), index=True, nullable=False)
    agent_id = Column(String, index=True, nullable=False)
    score = Column(Float, nullable=False)
    report = Column(Text)
    metrics = Column(JSONB)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    __table_args__ = (
        Index('idx_task_agent', 'task_id', 'agent_id'),
    )


class BinaryFileMetadata(Base):
    """MinIO binary file metadata table."""
    __tablename__ = "binary_file_metadata"
    
    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(String, index=True, nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id"), index=True, nullable=True)
    object_path = Column(String, unique=True, nullable=False, index=True)
    bucket = Column(String, index=True, nullable=False)
    content_type = Column(String)
    size_bytes = Column(Integer, default=0)
    file_metadata = Column("metadata", JSONB)  # Column name is "metadata" but attribute is file_metadata
    uploaded_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    __table_args__ = (
        Index('idx_agent_task', 'agent_id', 'task_id'),
        Index('idx_bucket_path', 'bucket', 'object_path'),
    )


class PostgresAdapter:
    """
    PostgreSQL adapter for task progress and metadata.
    
    Agents: Can write task progress and update status
    Evaluator: Can read all data and write evaluations
    """
    
    def __init__(self, connection_string: Optional[str] = None):
        """
        Initialize PostgreSQL adapter.
        
        Args:
            connection_string: PostgreSQL connection string. If None, uses POSTGRES_URL env var.
        """
        if connection_string:
            self.connection_string = connection_string
        else:
            self.connection_string = os.getenv(
                "POSTGRES_URL",
                "postgresql://hub:hubpassword@postgres:5432/hub"  # Using service name 'postgres' and default port 5432
            )
        
        self.engine = create_engine(self.connection_string)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        
        # Create tables if they don't exist
        Base.metadata.create_all(bind=self.engine)
    
    def create_task(
        self,
        agent_id: str,
        title: str,
        description: str,
        status: str = "pending",
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Create a new task record.
        
        Args:
            agent_id: Agent identifier
            title: Task title
            description: Task description
            status: Initial task status
            metadata: Optional task metadata
            
        Returns:
            Task ID
        """
        db = self.SessionLocal()
        try:
            task = Task(
                agent_id=agent_id,
                title=title,
                description=description,
                status=status,
                task_metadata=metadata or {}
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            return task.id
        finally:
            db.close()
    
    def update_task_status(
        self,
        task_id: int,
        status: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Update task status (agents can call this).
        
        Args:
            task_id: Task identifier
            status: New status
            metadata: Optional metadata updates
            
        Returns:
            True if updated, False otherwise
        """
        db = self.SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task:
                return False
            
            task.status = status
            task.updated_at = datetime.utcnow()
            
            if metadata:
                if task.task_metadata:
                    task.task_metadata.update(metadata)
                else:
                    task.task_metadata = metadata
            
            db.commit()
            return True
        finally:
            db.close()
    
    def add_progress_update(
        self,
        task_id: int,
        agent_id: str,
        progress_percent: float,
        message: str,
        data: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Add a progress update (agents can call this).
        
        Args:
            task_id: Task identifier
            agent_id: Agent identifier
            progress_percent: Progress percentage (0-100)
            message: Progress message
            data: Optional progress data
            
        Returns:
            Progress update ID
        """
        db = self.SessionLocal()
        try:
            progress = TaskProgress(
                task_id=task_id,
                agent_id=agent_id,
                progress_percent=progress_percent,
                message=message,
                data=data or {}
            )
            db.add(progress)
            db.commit()
            db.refresh(progress)
            return progress.id
        finally:
            db.close()
    
    def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a task by ID.
        
        Args:
            task_id: Task identifier
            
        Returns:
            Task record as dictionary or None
        """
        db = self.SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task:
                return None
            
            return {
                "id": task.id,
                "agent_id": task.agent_id,
                "title": task.title,
                "description": task.description,
                "status": task.status,
                "metadata": task.task_metadata,
                "created_at": task.created_at,
                "updated_at": task.updated_at
            }
        finally:
            db.close()
    
    def get_tasks(
        self,
        agent_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get tasks with optional filters.
        
        Args:
            agent_id: Filter by agent ID
            status: Filter by status
            limit: Maximum number of results
            
        Returns:
            List of task records
        """
        db = self.SessionLocal()
        try:
            query = db.query(Task)
            
            if agent_id:
                query = query.filter(Task.agent_id == agent_id)
            
            if status:
                query = query.filter(Task.status == status)
            
            tasks = query.order_by(Task.created_at.desc()).limit(limit).all()
            
            return [{
                "id": task.id,
                "agent_id": task.agent_id,
                "title": task.title,
                "description": task.description,
                "status": task.status,
                "metadata": task.task_metadata,
                "created_at": task.created_at,
                "updated_at": task.updated_at
            } for task in tasks]
        finally:
            db.close()
    
    def get_all_tasks(
        self,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        Get all tasks (used by evaluator scheduler).
        
        Args:
            limit: Maximum number of results
            
        Returns:
            List of task records
        """
        return self.get_tasks(agent_id=None, status=None, limit=limit)
    
    def get_task_progress(
        self,
        task_id: int,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get progress updates for a task.
        
        Args:
            task_id: Task identifier
            limit: Maximum number of results
            
        Returns:
            List of progress update records
        """
        db = self.SessionLocal()
        try:
            progress_updates = db.query(TaskProgress).filter(
                TaskProgress.task_id == task_id
            ).order_by(TaskProgress.timestamp.desc()).limit(limit).all()
            
            return [{
                "id": p.id,
                "task_id": p.task_id,
                "agent_id": p.agent_id,
                "progress_percent": p.progress_percent,
                "message": p.message,
                "data": p.data,
                "timestamp": p.timestamp
            } for p in progress_updates]
        finally:
            db.close()
    
    def create_evaluation(
        self,
        task_id: int,
        agent_id: str,
        score: float,
        report: str,
        metrics: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Create an evaluation record (evaluator use case).
        
        Args:
            task_id: Task identifier
            agent_id: Agent identifier
            score: Evaluation score
            report: Evaluation report
            metrics: Optional evaluation metrics
            
        Returns:
            Evaluation ID
        """
        db = self.SessionLocal()
        try:
            evaluation = Evaluation(
                task_id=task_id,
                agent_id=agent_id,
                score=score,
                report=report,
                metrics=metrics or {}
            )
            db.add(evaluation)
            db.commit()
            db.refresh(evaluation)
            return evaluation.id
        finally:
            db.close()
    
    def get_evaluations(
        self,
        task_id: Optional[int] = None,
        agent_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get evaluation records.
        
        Args:
            task_id: Filter by task ID
            agent_id: Filter by agent ID
            limit: Maximum number of results
            
        Returns:
            List of evaluation records
        """
        db = self.SessionLocal()
        try:
            query = db.query(Evaluation)
            
            if task_id:
                query = query.filter(Evaluation.task_id == task_id)
            
            if agent_id:
                query = query.filter(Evaluation.agent_id == agent_id)
            
            evaluations = query.order_by(Evaluation.created_at.desc()).limit(limit).all()
            
            return [{
                "id": e.id,
                "task_id": e.task_id,
                "agent_id": e.agent_id,
                "score": e.score,
                "report": e.report,
                "metrics": e.metrics,
                "created_at": e.created_at
            } for e in evaluations]
        finally:
            db.close()
    
    def register_binary_file(
        self,
        agent_id: str,
        object_path: str,
        bucket: str,
        content_type: str,
        task_id: Optional[int] = None,
        size_bytes: int = 0,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Register binary file metadata (called by MinIO adapter).
        
        Args:
            agent_id: Agent identifier
            object_path: MinIO object path
            bucket: MinIO bucket name
            content_type: MIME type
            task_id: Optional task identifier
            size_bytes: File size in bytes
            metadata: Optional additional metadata
            
        Returns:
            Metadata record ID
        """
        db = self.SessionLocal()
        try:
            file_metadata = BinaryFileMetadata(
                agent_id=agent_id,
                task_id=task_id,
                object_path=object_path,
                bucket=bucket,
                content_type=content_type,
                size_bytes=size_bytes,
                file_metadata=metadata or {}
            )
            db.add(file_metadata)
            db.commit()
            db.refresh(file_metadata)
            return file_metadata.id
        finally:
            db.close()
    
    def get_binary_files(
        self,
        agent_id: Optional[str] = None,
        task_id: Optional[int] = None,
        bucket: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get binary file metadata records.
        
        Args:
            agent_id: Filter by agent ID
            task_id: Filter by task ID
            bucket: Filter by bucket name
            limit: Maximum number of results
            
        Returns:
            List of binary file metadata records
        """
        db = self.SessionLocal()
        try:
            query = db.query(BinaryFileMetadata)
            
            if agent_id:
                query = query.filter(BinaryFileMetadata.agent_id == agent_id)
            
            if task_id:
                query = query.filter(BinaryFileMetadata.task_id == task_id)
            
            if bucket:
                query = query.filter(BinaryFileMetadata.bucket == bucket)
            
            files = query.order_by(BinaryFileMetadata.uploaded_at.desc()).limit(limit).all()
            
            return [{
                "id": f.id,
                "agent_id": f.agent_id,
                "task_id": f.task_id,
                "object_path": f.object_path,
                "bucket": f.bucket,
                "content_type": f.content_type,
                "size_bytes": f.size_bytes,
                "metadata": f.file_metadata,
                "uploaded_at": f.uploaded_at
            } for f in files]
        finally:
            db.close()

    def get_recent_progress(
        self,
        agent_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get recent task progress updates across tasks.

        Args:
            agent_id: Optional agent filter
            limit: Maximum number of results to return

        Returns:
            List of progress update records ordered from newest to oldest
        """
        db = self.SessionLocal()
        try:
            query = db.query(TaskProgress)

            if agent_id:
                query = query.filter(TaskProgress.agent_id == agent_id)

            progress_updates = (
                query
                .order_by(TaskProgress.timestamp.desc())
                .limit(limit)
                .all()
            )

            return [{
                "id": p.id,
                "task_id": p.task_id,
                "agent_id": p.agent_id,
                "progress_percent": p.progress_percent,
                "message": p.message,
                "data": p.data,
                "timestamp": p.timestamp
            } for p in progress_updates]
        finally:
            db.close()

    def get_recent_agent_messages(
        self,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Return recent agent-facing messages derived from task progress updates."""

        db = self.SessionLocal()
        try:
            query = (
                db.query(TaskProgress, Task)
                .outerjoin(Task, Task.id == TaskProgress.task_id)
                .order_by(TaskProgress.timestamp.desc())
                .limit(limit)
                .all()
            )

            messages: List[Dict[str, Any]] = []
            for progress, task in query:
                task_payload = None
                if task:
                    task_payload = {
                        "id": task.id,
                        "title": task.title,
                        "status": task.status,
                        "description": task.description,
                        "metadata": task.task_metadata,
                    }

                messages.append({
                    "id": progress.id,
                    "task_id": progress.task_id,
                    "agent_id": progress.agent_id,
                    "message": progress.message,
                    "progress_percent": progress.progress_percent,
                    "data": progress.data,
                    "timestamp": progress.timestamp,
                    "task": task_payload,
                })

            return messages
        finally:
            db.close()

    def get_unique_agents(self) -> List[str]:
        """
        Get list of unique agent IDs that have tasks in the database.
        
        Returns:
            List of unique agent IDs
        """
        db = self.SessionLocal()
        try:
            from sqlalchemy import distinct
            
            agents = db.query(distinct(Task.agent_id)).order_by(Task.agent_id).all()
            return [agent[0] for agent in agents if agent[0]]
        finally:
            db.close()

