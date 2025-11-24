"""
Main Server Application
=======================
FastAPI server for managing tasks, agents, and chat interface.
"""

import os
import time
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
import httpx

# Import storage adapters
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from storage import MongoAdapter, PostgresAdapter

from agent_manager import AgentManager

# Initialize FastAPI app
app = FastAPI(
    title="AI Village Server",
    version="1.0.0",
    description="Main server for task management and agent coordination"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize storage adapters
# Server connects to its own database for chat/system logs
# And uses cluster mode to read from individual agent databases
server_mongo = MongoAdapter(agent_id="server", connection_string=os.getenv("MONGODB_URL"))
agent_mongo = MongoAdapter(agent_id="server", connection_string=os.getenv("MONGODB_URL"), cluster_mode=True)

pg = PostgresAdapter(connection_string=os.getenv("POSTGRES_URL"))

# Initialize agent manager
agent_manager = AgentManager()

# Evaluator service URL (uses Docker service name)
EVALUATOR_URL = os.getenv("EVALUATOR_URL", "http://evaluator_agent:8001")

# Pydantic models
class TaskRequest(BaseModel):
    text: str
    timestamp: Optional[str] = None

class TaskResponse(BaseModel):
    task_id: int
    status: str
    message: str

class ChatMessageRequest(BaseModel):
    sender: str
    message: str
    reply_to: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class ChatMessageResponse(BaseModel):
    message_id: str
    sender: str
    message: str
    timestamp: str
    status: str
    task_id: Optional[int] = None
    agents_notified: Optional[int] = None

# Health check
@app.get("/health")
def health():
    return {"status": "ok"}

# Task endpoints
@app.post("/task", response_model=TaskResponse)
def create_task(task: TaskRequest):
    """Create a new task and add it to the queue for all agents to compete."""
    try:
        # Create 3 separate tasks - one for each agent to compete
        agent_ids = ["agent1", "agent2", "agent3"]
        task_ids = []
        
        for agent_id in agent_ids:
            task_id = pg.create_task(
                agent_id=agent_id,
                title=task.text[:100],  # Truncate for title
                description=task.text,
                status="pending"
            )
            task_ids.append(task_id)
            
            # Log task creation per agent
            server_mongo.write_log(
                level="info",
                message=f"Task created for {agent_id}: {task.text[:50]}...",
                task_id=str(task_id)
            )
        
        # Return the first task ID as the "primary" task
        return TaskResponse(
            task_id=task_ids[0],
            status="pending",
            message=f"Task created for all 3 agents (IDs: {', '.join(map(str, task_ids))})"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create task: {str(e)}")

@app.get("/tasks")
def get_tasks(limit: int = 50, status: Optional[str] = None):
    """Get list of tasks."""
    try:
        if status:
            tasks = pg.get_tasks(status=status, limit=limit)
        else:
            tasks = pg.get_tasks(limit=limit)
        return {"tasks": tasks, "count": len(tasks)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get tasks: {str(e)}")

@app.get("/task/{task_id}")
def get_task(task_id: int):
    """Get a specific task."""
    try:
        task = pg.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get task: {str(e)}")

# Chat endpoints
@app.post("/chat/send", response_model=ChatMessageResponse)
def send_chat_message(message: ChatMessageRequest):
    """Send a chat message. User messages create tasks automatically."""
    try:
        timestamp = datetime.now(timezone.utc)
        message_id = f"msg_{int(timestamp.timestamp() * 1000)}"
        
        # Store message in MongoDB (server DB)
        chat_doc = {
            "message_id": message_id,
            "sender": message.sender,
            "message": message.message,
            "reply_to": message.reply_to,
            "metadata": message.metadata or {},
            "timestamp": timestamp.isoformat(),
            "read_by": []
        }
        
        if server_mongo.db_name:
             server_mongo.client[server_mongo.db_name]["chat_messages"].insert_one(chat_doc)
        else:
             # Fallback if db_name logic in adapter is weird, but it shouldn't be
             server_mongo.client["serverdb"]["chat_messages"].insert_one(chat_doc)
        
        task_id = None
        agents_notified = None
        
        # If sender is "user", create 3 tasks - one for each agent to compete
        if message.sender == "user":
            agent_ids = ["agent1", "agent2", "agent3"]
            task_ids = []
            
            for agent_id in agent_ids:
                agent_task_id = pg.create_task(
                    agent_id=agent_id,
                    title=message.message[:100],
                    description=message.message,
                    status="pending",
                    metadata={"chat_message_id": message_id}
                )
                task_ids.append(agent_task_id)
                
                server_mongo.write_log(
                    level="info",
                    message=f"User message created task {agent_task_id} for {agent_id}",
                    task_id=str(agent_task_id)
                )
            
            # Use the first task ID as the primary task ID for the chat message
            task_id = task_ids[0]
            # All agents are notified (they each have their own task)
            agents_notified = 3  # agent1, agent2, agent3
        
        return ChatMessageResponse(
            message_id=message_id,
            sender=message.sender,
            message=message.message,
            timestamp=timestamp.isoformat(),
            status="sent",
            task_id=task_id,
            agents_notified=agents_notified
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send message: {str(e)}")

@app.get("/chat/history")
def get_chat_history(limit: int = 50, before: Optional[str] = None):
    """Get chat history."""
    try:
        collection = server_mongo.client[server_mongo.db_name or "serverdb"]["chat_messages"]
        
        query = {}
        if before:
            query["message_id"] = {"$lt": before}
        
        messages = list(collection
            .find(query)
            .sort("timestamp", -1)
            .limit(limit))
        
        # Convert ObjectId to string and format
        for msg in messages:
            msg["_id"] = str(msg["_id"])
        
        return {
            "messages": list(reversed(messages)),
            "count": len(messages),
            "has_more": len(messages) == limit
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get chat history: {str(e)}")

@app.post("/chat/reply", response_model=ChatMessageResponse)
def reply_to_message(message: ChatMessageRequest):
    """Reply to a specific chat message."""
    if not message.reply_to:
        raise HTTPException(status_code=400, detail="reply_to is required")
    
    return send_chat_message(message)

@app.get("/chat/messages/{message_id}")
def get_message(message_id: str):
    """Get a specific chat message."""
    try:
        collection = server_mongo.client[server_mongo.db_name or "serverdb"]["chat_messages"]
        message = collection.find_one({"message_id": message_id})
        
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
        
        message["_id"] = str(message["_id"])
        return message
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get message: {str(e)}")

@app.get("/chat/participants")
def get_participants():
    """Get all chat participants."""
    try:
        collection = server_mongo.client[server_mongo.db_name or "serverdb"]["chat_messages"]
        
        # Get message counts per sender
        pipeline = [
            {"$group": {"_id": "$sender", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        sender_counts = list(collection.aggregate(pipeline))
        
        participants = [
            {
                "id": "user",
                "type": "user",
                "message_count": next((s["count"] for s in sender_counts if s["_id"] == "user"), 0),
                "status": "active"
            }
        ]
        
        # Add agents
        for agent_id in ["agent1", "agent2", "agent3"]:
            participants.append({
                "id": agent_id,
                "type": "agent",
                "message_count": next((s["count"] for s in sender_counts if s["_id"] == agent_id), 0),
                "status": "online" if agent_manager.is_agent_running(agent_id) else "offline",
                "capabilities": ["computer_use", "web_automation"]
            })
        
        return {
            "participants": participants,
            "total": len(participants)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get participants: {str(e)}")

@app.get("/chat/stats")
def get_chat_stats():
    """Get chat statistics."""
    try:
        collection = server_mongo.client[server_mongo.db_name or "serverdb"]["chat_messages"]
        
        total = collection.count_documents({})
        user_messages = collection.count_documents({"sender": "user"})
        agent_messages = collection.count_documents({"sender": {"$in": ["agent1", "agent2", "agent3"]}})
        
        # Most active senders
        pipeline = [
            {"$group": {"_id": "$sender", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 5}
        ]
        most_active = list(collection.aggregate(pipeline))
        
        # Pending tasks
        pending_tasks = len(pg.get_tasks(status="pending", limit=100))
        
        return {
            "total_messages": total,
            "user_messages": user_messages,
            "agent_messages": agent_messages,
            "most_active": [{"sender": s["_id"], "count": s["count"]} for s in most_active],
            "registered_agents": 3,
            "pending_tasks": pending_tasks
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")

# Agent management endpoints
@app.get("/agents/status")
def get_agent_status():
    """Get status of all agents."""
    return agent_manager.get_status()

@app.post("/agents/start/{agent_id}")
def start_agent(agent_id: str):
    """Start a specific agent."""
    success = agent_manager.start_agent(agent_id)
    if success:
        return {"status": "started", "agent_id": agent_id}
    else:
        raise HTTPException(status_code=500, detail=f"Failed to start agent {agent_id}")

@app.post("/agents/stop/{agent_id}")
def stop_agent(agent_id: str):
    """Stop a specific agent."""
    agent_manager.stop_agent(agent_id)
    return {"status": "stopped", "agent_id": agent_id}

@app.get("/chat/agent-responses")
def get_agent_responses(limit: int = 60):
    """Get agent responses from MongoDB logs, joined with task information.
    Also includes user messages from chat history to ensure they persist.
    Filters out system messages like 'Task picked', 'Task completed' and prioritizes meaningful agent content.
    """
    try:
        agent_ids = ["agent1", "agent2", "agent3"]
        all_items = []
        
        # 1. Fetch logs from each agent's database using cluster mode adapter
        for agent_id in agent_ids:
            try:
                # Filter out debug logs at query level
                logs = agent_mongo.read_logs(
                    agent_id=agent_id,
                    level={"$ne": "debug"},
                    limit=limit * 2
                )
                for log in logs:
                    # Add type to distinguish source
                    log["_source_type"] = "log"
                    all_items.append(log)
            except Exception as e:
                print(f"Warning: Failed to read logs for {agent_id}: {e}")
        
        # 2. Fetch user chat messages
        try:
            collection = server_mongo.client[server_mongo.db_name or "serverdb"]["chat_messages"]
            chat_messages = list(collection
                .find({"sender": "user"})
                .sort("timestamp", -1)
                .limit(limit))
            
            for msg in chat_messages:
                # Convert chat message to similar structure as logs
                all_items.append({
                    "_id": str(msg["_id"]),
                    "id": msg["message_id"],
                    "agent_id": "user",
                    "message": msg["message"],
                    "timestamp": msg["timestamp"],
                    "_source_type": "chat",
                    "task_id": None, # Could try to extract from metadata if needed
                    "metadata": msg.get("metadata", {})
                })
        except Exception as e:
            print(f"Warning: Failed to read chat messages: {e}")

        # System message patterns to exclude
        system_message_patterns = [
            "task picked:",
            "task completed",
            "trajectory processed:",
            "agent worker started",
            "agent worker stopped",
            "execution result",
            "agent_response_start",
            "agent_response_end",
            "execute_task.py stdout",
            "execute_task.py stderr",
            "execute_task.py completed",
        ]
        
        def is_system_message(message_text: str, metadata: dict, source_type: str) -> bool:
            """Check if a message is a system message that should be filtered out."""
            # Always keep chat messages
            if source_type == "chat":
                return False

            if not message_text:
                return True
            
            message_lower = message_text.lower().strip()
            
            # Check metadata first - if it's from agent output, trajectory, or marked as agent_response, keep it
            if metadata:
                source = metadata.get("source")
                msg_type = metadata.get("type")
                if source in ["trajectory", "agent_output"] or msg_type == "agent_response":
                    return False
            
            # Check if message matches any system pattern
            for pattern in system_message_patterns:
                if pattern in message_lower:
                    return True
            
            # Default: keep the message (it's likely meaningful)
            return False
        
        # Filter out system messages and prioritize meaningful content
        meaningful_items = []
        for item in all_items:
            message_text = item.get("message", "")
            metadata = item.get("metadata", {})
            source_type = item.get("_source_type", "log")
            
            # Skip system messages
            if is_system_message(message_text, metadata, source_type):
                continue
            
            # Prioritize messages from trajectory, agent output, or user chat
            priority = 0
            if source_type == "chat":
                priority = 2 # Highest priority for user messages
            elif metadata.get("source") in ["trajectory", "agent_output"] or metadata.get("type") == "agent_response":
                priority = 1
            
            meaningful_items.append((priority, item))
        
        # Sort by timestamp chronologically (oldest first)
        def get_sort_key(entry):
            priority, item = entry
            # MongoDB stores timestamp as 'created_at' or 'timestamp'
            timestamp = item.get("created_at") or item.get("timestamp")
            
            # Convert timestamp to comparable value
            if isinstance(timestamp, datetime):
                ts_value = timestamp.timestamp()
            elif isinstance(timestamp, str):
                try:
                    ts_value = datetime.fromisoformat(timestamp.replace('Z', '+00:00')).timestamp()
                except:
                    ts_value = 0
            else:
                ts_value = 0
            return ts_value
        
        meaningful_items.sort(key=get_sort_key, reverse=False)  # Oldest first for chronological order
        
        # Get the top meaningful items (keep last N to respect limit)
        # We want the most recent 'limit' items, but sorted chronologically
        # So we take the last 'limit' items from the sorted list
        filtered_items = [item for _, item in meaningful_items[-limit:]]
        
        # Get task IDs from filtered logs (for agents)
        task_ids = set()
        for item in filtered_items:
            if item.get("task_id"):
                try:
                    task_ids.add(int(item["task_id"]))
                except (ValueError, TypeError):
                    pass
        
        # Fetch task information from PostgreSQL
        task_map = {}
        if task_ids:
            for task_id in task_ids:
                try:
                    task = pg.get_task(task_id)
                    if task:
                        task_map[task_id] = {
                            "id": task.get("id"),
                            "title": task.get("title"),
                            "status": task.get("status"),
                            "description": task.get("description")
                        }
                except Exception:
                    pass
        
        # Get progress information for tasks from task_progress table
        progress_map = {}
        for task_id in task_ids:
            try:
                progress_list = pg.get_task_progress(task_id, limit=1)
                if progress_list:
                    latest = progress_list[0]
                    progress_map[task_id] = latest.get("progress_percent") or latest.get("percent")
            except Exception:
                pass
        
        # Format response
        messages = []
        for item in filtered_items:
            try:
                item_id = str(item.get("id") or item.get("_id", ""))
                agent_id = item.get("agent_id", "agent")
                message_text = item.get("message", "")
                # MongoDB stores timestamp as 'created_at', use that as primary source
                timestamp = item.get("created_at") or item.get("timestamp")
                task_id = None
                
                # Skip empty messages
                if not message_text or not message_text.strip():
                    continue
                
                # Extract task_id
                if item.get("task_id"):
                    try:
                        task_id = int(item["task_id"])
                    except (ValueError, TypeError):
                        pass
                
                # Get task info
                task_info = None
                if task_id and task_id in task_map:
                    task_info = task_map[task_id]
                
                # Get progress
                progress_percent = None
                if task_id and task_id in progress_map:
                    progress_percent = progress_map[task_id]
                
                # Format timestamp - ensure proper conversion
                if isinstance(timestamp, datetime):
                    pass
                elif isinstance(timestamp, str):
                    try:
                        timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    except:
                        try:
                            # Try parsing ISO format with Z
                            timestamp = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
                        except:
                            timestamp = datetime.now(timezone.utc)
                elif not timestamp:
                    timestamp = datetime.now(timezone.utc)
                
                messages.append({
                    "id": item_id,
                    "agent_id": agent_id,
                    "message": message_text,
                    "timestamp": timestamp.isoformat() if isinstance(timestamp, datetime) else str(timestamp),
                    "task_id": task_id,
                    "progress_percent": progress_percent,
                    "task": task_info
                })
            except Exception as e:
                # Skip malformed logs
                continue
        
        # Sort by timestamp ascending (chronological order - oldest first)
        messages.sort(key=lambda x: x.get("timestamp", ""), reverse=False)
        
        return {
            "messages": messages,
            "count": len(messages)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get agent responses: {str(e)}")

# Evaluator proxy endpoints
@app.get("/evaluator/status")
async def evaluator_status():
    """Proxy to evaluator status endpoint."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{EVALUATOR_URL}/status")
            return response.json()
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Evaluator service unavailable: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get evaluator status: {str(e)}")

@app.get("/evaluator/reports")
async def evaluator_reports():
    """Proxy to evaluator reports endpoint."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{EVALUATOR_URL}/reports")
            return response.json()
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Evaluator service unavailable: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get evaluator reports: {str(e)}")

@app.get("/evaluator/agent/{agent_id}")
async def evaluator_agent_reports(agent_id: str):
    """Proxy to evaluator agent reports endpoint."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{EVALUATOR_URL}/agent/{agent_id}")
            if response.status_code == 404:
                raise HTTPException(status_code=404, detail="No reports for agent")
            return response.json()
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Evaluator service unavailable: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get agent reports: {str(e)}")

@app.get("/evaluator/task/{task_id}")
async def evaluator_task_report(task_id: str):
    """Proxy to evaluator task report endpoint."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{EVALUATOR_URL}/task/{task_id}")
            if response.status_code == 404:
                raise HTTPException(status_code=404, detail="Task report not found")
            return response.json()
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Evaluator service unavailable: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get task report: {str(e)}")

@app.get("/evaluator/agents/progress/graph")
async def evaluator_progress_graph():
    """Proxy to evaluator progress graph endpoint."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:  # Longer timeout for graph generation
            response = await client.get(f"{EVALUATOR_URL}/agents/progress/graph")
            return response.json()
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Evaluator service unavailable: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate progress graph: {str(e)}")

@app.get("/agents/live")
def get_agents_live(limit_per_agent: int = 10):
    """Get live agent data including progress."""
    try:
        agent_ids = ["agent1", "agent2", "agent3"]
        agents_data = []
        
        for agent_id in agent_ids:
            # Get progress info
            latest_progress = None
            progress_updates = []
            try:
                # Use PostgresAdapter to get recent progress
                if hasattr(pg, "get_recent_progress"):
                    progress_list = pg.get_recent_progress(agent_id=agent_id, limit=5)
                    if progress_list:
                        latest_progress = progress_list[0]
                        progress_updates = progress_list
            except Exception as e:
                # Log error but don't fail request
                print(f"Failed to get progress for {agent_id}: {e}")
            
            # Build agent data
            agents_data.append({
                "agent_id": agent_id,
                "latest_progress": latest_progress,
                "progress_updates": progress_updates
            })
        
        return {
            "agents": agents_data,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get agents live data: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
