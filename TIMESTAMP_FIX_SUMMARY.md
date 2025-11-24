# Chronological Order Fix - Agent Task Responses

## Problem
Agent task responses were not appearing in chronological order in the chat. Messages from different agents were interleaved incorrectly because timestamps were being set when logs were written to MongoDB (processing time), not when the actual agent responses occurred (execution time).

## Root Cause
1. **MongoDB auto-timestamps**: The `MongoSchema.log_entry()` method was using `datetime.utcnow()` at the time of database insertion
2. **Async processing**: The trajectory processor processes files asynchronously, so all messages from a trajectory file got the same timestamp (when processed), not when generated
3. **No timestamp extraction**: Trajectory file paths contain accurate timestamps (e.g., `2025-11-23_omni_gpt5_215429_f354`), but these weren't being extracted and used

## Solution
Modified the timestamp handling to extract accurate timestamps from trajectory file paths and use them when logging to MongoDB.

### Changes Made

#### 1. Updated `storage/schemas.py`
- Added optional `timestamp` parameter to `MongoSchema.log_entry()`
- Now accepts explicit timestamps instead of always using current time
- Stores timestamp in both `created_at` and `timestamp` fields for compatibility

```python
@staticmethod
def log_entry(
    level: str,
    message: str,
    agent_id: str,
    task_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    timestamp: Optional[datetime] = None  # NEW: Optional explicit timestamp
) -> Dict[str, Any]:
    entry_time = timestamp if timestamp is not None else datetime.utcnow()
    return {
        "level": level,
        "message": message,
        "agent_id": agent_id,
        "task_id": task_id,
        "metadata": metadata or {},
        "created_at": entry_time,
        "timestamp": entry_time
    }
```

#### 2. Updated `storage/mongo_adapter.py`
- Added `timestamp` parameter to `write_log()` method
- Passes timestamp through to `MongoSchema.log_entry()`

```python
def write_log(
    self,
    level: str,
    message: str,
    task_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    timestamp: Optional[datetime] = None  # NEW
) -> str:
    log_entry = MongoSchema.log_entry(
        level=level,
        message=message,
        agent_id=self.agent_id,
        task_id=task_id,
        metadata=metadata,
        timestamp=timestamp  # Pass through
    )
    result = self.logs.insert_one(log_entry)
    return str(result.inserted_id)
```

#### 3. Updated `agents/*/agent_worker/trajectory_processor.py`
- Added `_extract_timestamp_from_path()` method to parse timestamps from file paths
- Extracts timestamps from directory names like:
  - `2025-11-23_omni_gpt5_215429_f354` → `2025-11-23 21:54:29`
  - `20251123_215419_520685` → `2025-11-23 21:54:19`
- Passes extracted timestamp to `write_log()` calls

```python
def _extract_timestamp_from_path(self, file_path: Path) -> Optional[datetime]:
    """Extract timestamp from trajectory file path."""
    try:
        parent_dir = file_path.parent.name
        # Parse formats like: 2025-11-23_omni_gpt5_215429_f354
        if '_' in parent_dir:
            parts = parent_dir.split('_')
            if len(parts) >= 4:
                date_str = parts[0]  # 2025-11-23
                time_str = parts[3]  # 215429
                # ... parse and return datetime
    except Exception as e:
        print(f"Warning: Could not extract timestamp: {e}")
    return None

def _process_file(self, file_path: Path):
    # Extract timestamp from file path
    file_timestamp = self._extract_timestamp_from_path(file_path)
    
    # Use extracted timestamp when logging
    self.mongo.write_log(
        task_id=self.task_id,
        level="info",
        message=msg,
        meta={"type": "agent_response", "source": "trajectory", "file": file_path.name},
        timestamp=file_timestamp  # Use file timestamp, not current time
    )
```

## Verification

### Test Results
```
Total messages fetched: 30
✅ Messages are in chronological order: True
✅ All messages have timestamps: True
✅ Timestamps are from code (not MongoDB auto): ✅
✅ Timestamps extracted from trajectory files: ✅
```

### Example Output
```
2025-11-23T22:17:38.155000 | agent2   | All agents working correctly!
2025-11-23T22:21:23.052000 | agent2   | Agent 1 fixed and working!
2025-11-23T22:29:07.946000 | agent2   | Agent 1 new container working!
2025-11-23T22:30:56.600000 | agent3   | All three agents working perfectly!
2025-11-23T22:31:00.266000 | agent2   | All three agents working perfectly!
2025-11-23T22:31:00.776000 | agent1   | All three agents working perfectly!
```

## Impact
- ✅ **Chronological Order**: Messages now appear in the correct order based on when they were actually generated
- ✅ **Accurate Timestamps**: Timestamps reflect actual agent execution time, not processing time
- ✅ **No Breaking Changes**: Backward compatible - falls back to current time if no timestamp provided
- ✅ **All Agents**: Applied to agent1, agent2, and agent3

## Files Modified
1. `storage/schemas.py` - Added timestamp parameter to log_entry()
2. `storage/mongo_adapter.py` - Added timestamp parameter to write_log()
3. `agents/agent1/agent_worker/trajectory_processor.py` - Extract and use file timestamps
4. `agents/agent2/agent_worker/trajectory_processor.py` - Extract and use file timestamps
5. `agents/agent3/agent_worker/trajectory_processor.py` - Extract and use file timestamps

## Deployment
1. Updated storage schema and adapter
2. Updated trajectory processors for all agents
3. Rebuilt agent worker containers
4. Restarted all agent workers
5. Verified chronological ordering

## Notes
- Timestamps are now set in **application code**, not by MongoDB
- Trajectory file paths contain accurate execution timestamps
- The fix ensures messages appear in the order they were actually generated by the agents
- Server-side sorting (`server/main.py`) already sorts by timestamp ascending, so no changes needed there
