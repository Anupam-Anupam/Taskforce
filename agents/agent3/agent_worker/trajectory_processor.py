"""
Lean trajectory processor - watches CUA trajectory files and stores in MongoDB.
"""
import json
import base64
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Import db_adapters - try absolute first (for direct execution), then relative (for package import)
try:
    from db_adapters import MongoClientWrapper
except ImportError:
    try:
        from .db_adapters import MongoClientWrapper
    except ImportError:
        # Last resort: add current directory to path
        import sys
        from pathlib import Path
        current_dir = Path(__file__).parent
        if str(current_dir) not in sys.path:
            sys.path.insert(0, str(current_dir))
        from db_adapters import MongoClientWrapper


class TrajectoryProcessor(FileSystemEventHandler):
    """Processes CUA trajectory files in real-time and stores in MongoDB."""
    
    def __init__(self, trajectory_dir: Path, mongo_client: MongoClientWrapper, task_id: Optional[int] = None):
        self.trajectory_dir = Path(trajectory_dir)
        self.mongo = mongo_client
        self.task_id = task_id
        self.processed_files = set()
        
        # Ensure directory exists
        self.trajectory_dir.mkdir(parents=True, exist_ok=True)
        
        # Process existing files
        self._process_existing()
    
    def _extract_messages_from_json(self, data: Dict[str, Any]) -> List[str]:
        """Extract all meaningful messages/results from JSON data using multiple schema patterns."""
        messages = []
        
        if not isinstance(data, dict):
            return messages
        
        # Schema 1: response.output structure
        if "response" in data:
            response = data["response"]
            if isinstance(response, dict) and "output" in response:
                output = response["output"]
                if isinstance(output, list):
                    for item in output:
                        if isinstance(item, dict) and item.get("type") == "message":
                            content = item.get("content", [])
                            if isinstance(content, list):
                                for content_item in content:
                                    if isinstance(content_item, dict):
                                        # Try output_text type
                                        if content_item.get("type") == "output_text":
                                            text = content_item.get("text")
                                            if isinstance(text, str) and text.strip():
                                                messages.append(text.strip())
                                        # Try direct text field
                                        elif "text" in content_item:
                                            text = content_item.get("text")
                                            if isinstance(text, str) and text.strip():
                                                messages.append(text.strip())
        
        # Schema 2: direct output structure
        if "output" in data:
            output = data["output"]
            if isinstance(output, list):
                for item in output:
                    if isinstance(item, dict) and item.get("type") == "message":
                        content = item.get("content", [])
                        if isinstance(content, list):
                            for content_item in content:
                                if isinstance(content_item, dict):
                                    # Try output_text type
                                    if content_item.get("type") == "output_text":
                                        text = content_item.get("text")
                                        if isinstance(text, str) and text.strip():
                                            messages.append(text.strip())
                                    # Try direct text field
                                    elif "text" in content_item:
                                        text = content_item.get("text")
                                        if isinstance(text, str) and text.strip():
                                            messages.append(text.strip())
                        # Also check if content is a string directly
                        elif isinstance(content, str) and content.strip():
                            messages.append(content.strip())
        
        # Schema 3: role-based messages (assistant role)
        if data.get("role") == "assistant":
            if "content" in data:
                content = data["content"]
                if isinstance(content, str) and content.strip():
                    messages.append(content.strip())
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and "text" in item:
                            text = item.get("text")
                            if isinstance(text, str) and text.strip():
                                messages.append(text.strip())
                        elif isinstance(item, str) and item.strip():
                            messages.append(item.strip())
        
        # Schema 4: direct text/result fields
        for field in ["text", "result", "message", "content", "response_text"]:
            if field in data:
                value = data[field]
                if isinstance(value, str) and value.strip():
                    messages.append(value.strip())
                elif isinstance(value, dict) and "text" in value:
                    text = value.get("text")
                    if isinstance(text, str) and text.strip():
                        messages.append(text.strip())
        
        # Schema 5: nested result/response structures
        if "result" in data and isinstance(data["result"], dict):
            result = data["result"]
            if "text" in result:
                text = result.get("text")
                if isinstance(text, str) and text.strip():
                    messages.append(text.strip())
            if "output" in result:
                output = result["output"]
                if isinstance(output, str) and output.strip():
                    messages.append(output.strip())
        
        return messages
    
    def _process_existing(self):
        """Process any existing trajectory files."""
        if not self.trajectory_dir.exists():
            return
        
        for file_path in self.trajectory_dir.rglob("*.json"):
            if str(file_path) not in self.processed_files:
                self._process_file(file_path)
    
    def _process_file(self, file_path: Path):
        """Process a single trajectory file."""
        if str(file_path) in self.processed_files:
            return
        
        try:
            print(f"[TrajectoryProcessor] Processing file: {file_path}")
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.processed_files.add(str(file_path))
            print(f"[TrajectoryProcessor] File loaded, keys: {list(data.keys()) if isinstance(data, dict) else 'not a dict'}")
            
            # Extract meaningful messages/results from JSON
            extracted_messages = []
            if isinstance(data, dict):
                extracted_messages = self._extract_messages_from_json(data)
                
                # Log each extracted message
                for msg in extracted_messages:
                    if msg:  # Only log non-empty messages
                        print(f"[TrajectoryProcessor] Extracted message: {msg[:100]}...")
                        self.mongo.write_log(
                            task_id=self.task_id,
                            level="info",
                            message=msg,
                            meta={"type": "agent_response", "source": "trajectory", "file": file_path.name}
                        )
                
                # Extract agent responses from output (legacy support)
                if "output" in data:
                    for item in data.get("output", []):
                        if item.get("type") == "message":
                            content = item.get("content", [])
                            for cp in content:
                                if isinstance(cp, dict):
                                    # Image processing removed - VNC stream used instead
                                    pass
                
                # Check for nested trajectory data
                if "trajectory" in data:
                    self._process_trajectory_data(data["trajectory"])
            
            # Store a summary log entry (only if no messages were extracted, to avoid duplicate logs)
            if not extracted_messages:
                self.mongo.write_log(
                    task_id=self.task_id,
                    level="debug",
                    message=f"Trajectory processed: {file_path.name}",
                    meta={"trajectory_file": str(file_path), "data": data}
                )
            else:
                # Store a brief summary log with count of messages extracted
                self.mongo.write_log(
                    task_id=self.task_id,
                    level="debug",
                    message=f"Trajectory processed: {file_path.name} ({len(extracted_messages)} messages extracted)",
                    meta={"trajectory_file": str(file_path), "messages_count": len(extracted_messages)}
                )
            
        except Exception as e:
            print(f"Error processing trajectory {file_path}: {e}")
    
    
    def _process_trajectory_data(self, trajectory_data: Any):
        """Recursively process nested trajectory data."""
        if isinstance(trajectory_data, dict):
            # Screenshot processing removed - VNC stream used instead
            
            # Recursively process nested dicts
            for value in trajectory_data.values():
                if isinstance(value, (dict, list)):
                    self._process_trajectory_data(value)
        elif isinstance(trajectory_data, list):
            for item in trajectory_data:
                if isinstance(item, (dict, list)):
                    self._process_trajectory_data(item)
    
    def on_created(self, event):
        """Handle new file creation."""
        if event.is_directory:
            return
        
        if event.src_path.endswith('.json'):
            self._process_file(Path(event.src_path))
    
    def on_modified(self, event):
        """Handle file modification."""
        if event.is_directory:
            return
        
        if event.src_path.endswith('.json'):
            self._process_file(Path(event.src_path))


def start_processor(trajectory_dir: Path, mongo_client: MongoClientWrapper, task_id: Optional[int] = None) -> Observer:
    """Start watching trajectory directory."""
    processor = TrajectoryProcessor(trajectory_dir, mongo_client, task_id)
    observer = Observer()
    observer.schedule(processor, str(trajectory_dir), recursive=True)
    observer.start()
    return observer

