import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from storage import MongoAdapter, PostgresAdapter


class DataCollector:
    """Collects and normalizes data across Mongo and Postgres."""

    def __init__(self, mongo: MongoAdapter, pg: PostgresAdapter, logger: Optional[logging.Logger] = None) -> None:
        self.mongo = mongo
        self.pg = pg
        self.logger = logger or logging.getLogger(__name__)
        self.default_agent_id = os.getenv("DEFAULT_AGENT_ID")

    def _normalize_id(self, v: Any) -> Optional[str]:
        if v is None:
            return None
        return str(v)

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def collect_for_task(self, agent_id: Optional[str], task_id: str) -> Dict[str, Any]:
        agent_id = self._normalize_id(agent_id or self.default_agent_id)
        task_id = self._normalize_id(task_id)

        logs = self.mongo.fetch_task_logs(agent_id, task_id)
        
        # Log what we found for debugging
        self.logger.info(json.dumps({
            "event": "fetch_task_logs_result",
            "agent_id": agent_id,
            "task_id": task_id,
            "log_count": len(logs),
            "log_levels": [l.get("level") for l in logs[:10]],  # First 10 log levels
            "log_messages_sample": [l.get("message", "")[:50] for l in logs[:5]]  # First 5 message previews
        }))
        
        metrics = self.mongo.compute_basic_metrics(logs)
        progress = self.pg.get_task_progress(task_id)

        # Extract metrics from CUA logs (stderr field contains usage statistics)
        mem_usage = 0.0
        cpu_usage = 0.0
        cost_usd = 0.0
        total_api_calls = 0
        completion_tokens = 0
        prompt_tokens = 0
        total_tokens = 0
        
        # First, search for "Total usage" logs (most common format from ComputerAgent)
        # These are INFO level logs with metrics in the message
        for l in logs:
            message = l.get("message", "")
            level = l.get("level", "")
            
            # Look for "Total usage" pattern (this is the format from ComputerAgent)
            if message and "Total usage" in message:
                # Normalize the message - handle both literal \n and actual newlines
                # Replace literal \n with actual newlines for easier parsing
                normalized_message = message.replace("\\n", "\n")
                
                # Extract all metrics from this format
                # Pattern: " - completion_tokens: 172" or "completion_tokens: 172"
                comp_tokens_match = re.search(r"completion_tokens:\s*([0-9]+)", normalized_message)
                if comp_tokens_match:
                    try:
                        completion_tokens = int(comp_tokens_match.group(1))  # Use latest value
                    except Exception:
                        pass
                
                prompt_tokens_match = re.search(r"prompt_tokens:\s*([0-9]+)", normalized_message)
                if prompt_tokens_match:
                    try:
                        prompt_tokens = int(prompt_tokens_match.group(1))  # Use latest value
                    except Exception:
                        pass
                
                total_tokens_match = re.search(r"total_tokens:\s*([0-9]+)", normalized_message)
                if total_tokens_match:
                    try:
                        total_tokens = int(total_tokens_match.group(1))  # Use latest value
                    except Exception:
                        pass
                
                # Extract response_cost - handle both "$0.0319" and "0.0319" formats
                cost_match = re.search(r"response_cost:\s*\$?([0-9]+(?:\.[0-9]+)?)", normalized_message)
                if cost_match:
                    try:
                        cost_val = float(cost_match.group(1))
                        cost_usd += cost_val  # Sum all costs
                        total_api_calls += 1
                    except Exception:
                        pass
                
                self.logger.info(json.dumps({
                    "event": "found_total_usage_log",
                    "level": level,
                    "extracted_cost": cost_usd,
                    "extracted_tokens": {"completion": completion_tokens, "prompt": prompt_tokens, "total": total_tokens}
                }))
        
        # Fallback: search for other formats (stderr, etc.)
        stderr_logs_found = 0
        for l in logs:
            metadata = l.get("metadata", {})
            message = l.get("message", "")
            level = l.get("level", "")
            
            # Skip if we already processed this as a "Total usage" log
            if message and "Total usage" in message:
                continue
            
            # Check stderr field in metadata for CUA usage statistics
            stderr = metadata.get("stderr", "")
            
            # Also check if the message itself contains stderr data
            if not stderr and message and "stderr" in message.lower():
                if "execute_task.py stderr" in message or "stderr" in message.lower():
                    stderr = message
            
            # If still no stderr, check if metadata has the data directly
            if not stderr:
                if "response_cost" in str(metadata) or "completion_tokens" in str(metadata):
                    stderr = str(metadata)
            
            # Extract from stderr string (whether from metadata.stderr or message)
            if stderr and isinstance(stderr, str):
                # Extract response_cost
                cost_match = re.search(r"response_cost:\s*\$?([0-9]+(?:\.[0-9]+)?)", stderr)
                if cost_match and cost_usd == 0.0:  # Only if not already found
                    try:
                        cost_val = float(cost_match.group(1))
                        cost_usd += cost_val
                        total_api_calls += 1
                    except Exception:
                        pass
                
                # Extract token counts (only if not already found)
                if completion_tokens == 0:
                    comp_tokens_match = re.search(r"completion_tokens:\s*([0-9]+)", stderr)
                    if comp_tokens_match:
                        try:
                            completion_tokens = int(comp_tokens_match.group(1))
                        except Exception:
                            pass
                
                if prompt_tokens == 0:
                    prompt_tokens_match = re.search(r"prompt_tokens:\s*([0-9]+)", stderr)
                    if prompt_tokens_match:
                        try:
                            prompt_tokens = int(prompt_tokens_match.group(1))
                        except Exception:
                            pass
                
                if total_tokens == 0:
                    total_tokens_match = re.search(r"total_tokens:\s*([0-9]+)", stderr)
                    if total_tokens_match:
                        try:
                            total_tokens = int(total_tokens_match.group(1))
                        except Exception:
                            pass
        
        # If we didn't find any metrics, try searching recent agent logs (last 10 logs)
        # This handles cases where the "Total usage" log might have a different task_id
        if cost_usd == 0.0 and total_api_calls == 0:
            self.logger.info(json.dumps({
                "event": "no_metrics_found_in_task_logs",
                "agent_id": agent_id,
                "task_id": task_id,
                "trying_recent_agent_logs": True
            }))
            
            # Try fetching recent logs for this agent (without task_id filter)
            try:
                recent_agent_logs = self.mongo.read_logs(
                    agent_id=agent_id,
                    limit=10  # Get last 10 logs (should include the "Total usage" log)
                )
                
                self.logger.info(json.dumps({
                    "event": "searching_recent_logs",
                    "recent_log_count": len(recent_agent_logs),
                    "sample_messages": [l.get("message", "")[:50] for l in recent_agent_logs[:3]]
                }))
                
                # Search through recent logs for "Total usage" pattern
                for l in recent_agent_logs:
                    message = l.get("message", "")
                    
                    # Look for "Total usage" pattern (primary format)
                    if message and "Total usage" in message:
                        # Normalize the message - handle both literal \n and actual newlines
                        normalized_message = message.replace("\\n", "\n")
                        
                        # Extract metrics
                        comp_tokens_match = re.search(r"completion_tokens:\s*([0-9]+)", normalized_message)
                        if comp_tokens_match:
                            try:
                                completion_tokens = int(comp_tokens_match.group(1))
                            except Exception:
                                pass
                        
                        prompt_tokens_match = re.search(r"prompt_tokens:\s*([0-9]+)", normalized_message)
                        if prompt_tokens_match:
                            try:
                                prompt_tokens = int(prompt_tokens_match.group(1))
                            except Exception:
                                pass
                        
                        total_tokens_match = re.search(r"total_tokens:\s*([0-9]+)", normalized_message)
                        if total_tokens_match:
                            try:
                                total_tokens = int(total_tokens_match.group(1))
                            except Exception:
                                pass
                        
                        cost_match = re.search(r"response_cost:\s*\$?([0-9]+(?:\.[0-9]+)?)", normalized_message)
                        if cost_match:
                            try:
                                cost_val = float(cost_match.group(1))
                                cost_usd += cost_val
                                total_api_calls += 1
                                self.logger.info(json.dumps({
                                    "event": "found_metrics_in_recent_logs",
                                    "cost": cost_val,
                                    "tokens": {"completion": completion_tokens, "prompt": prompt_tokens, "total": total_tokens}
                                }))
                            except Exception:
                                pass
                        break  # Found it, no need to continue
            except Exception as e:
                self.logger.warning(json.dumps({
                    "event": "fallback_log_search_failed",
                    "error": str(e)
                }))

        # Get task information including description and final output
        task_info = None
        initial_request = ""
        final_output = ""
        try:
            # Try to convert task_id to integer
            task_id_int = None
            if isinstance(task_id, int):
                task_id_int = task_id
            elif isinstance(task_id, str):
                if task_id.isdigit():
                    task_id_int = int(task_id)
                else:
                    # Try to extract number from string
                    import re
                    match = re.search(r'(\d+)', task_id)
                    if match:
                        task_id_int = int(match.group(1))
            
            if task_id_int:
                task_info = self.pg.get_task(task_id_int)
                if task_info:
                    # Get initial request from description or metadata
                    initial_request = task_info.get("description", "") or ""
                    
                    # If description is empty, try to get from metadata
                    if not initial_request:
                        metadata = task_info.get("metadata", {})
                        if isinstance(metadata, dict):
                            # Try various possible fields for initial request
                            initial_request = (
                                metadata.get("input_text", "") or
                                metadata.get("input_data", {}).get("input_text", "") if isinstance(metadata.get("input_data"), dict) else "" or
                                metadata.get("task_description", "") or
                                ""
                            )
                    
                    # Get final output from metadata
                    metadata = task_info.get("metadata", {})
                    if isinstance(metadata, dict):
                        # Try various possible fields for final output
                        output_data = metadata.get("output_data", {})
                        if isinstance(output_data, dict):
                            final_output = (
                                output_data.get("response", "") or
                                output_data.get("result", "") or
                                output_data.get("output", "") or
                                str(output_data) if output_data else ""
                            )
                        # Also check if output is directly in metadata
                        if not final_output:
                            final_output = (
                                metadata.get("response", "") or
                                metadata.get("result", "") or
                                metadata.get("output", "") or
                                ""
                            )
                    
                    self.logger.info(json.dumps({
                        "event": "task_info_collected",
                        "task_id": task_id,
                        "has_initial_request": bool(initial_request),
                        "has_final_output": bool(final_output),
                        "request_length": len(initial_request),
                        "output_length": len(final_output),
                        "task_status": task_info.get("status", "")
                    }))
                else:
                    self.logger.warning(json.dumps({
                        "event": "task_not_found",
                        "task_id": task_id,
                        "task_id_int": task_id_int
                    }))
            else:
                self.logger.warning(json.dumps({
                    "event": "task_id_conversion_failed",
                    "task_id": task_id,
                    "task_id_type": type(task_id).__name__
                }))
        except Exception as e:
            self.logger.warning(json.dumps({
                "event": "task_info_fetch_error",
                "task_id": task_id,
                "error": str(e),
                "error_type": type(e).__name__
            }))
        
        data = {
            "agent_id": agent_id,
            "task_id": task_id,
            "logs": logs,
            "metrics": {
                **metrics,
                "memory_usage_mb": mem_usage,
                "cpu_usage_percent": cpu_usage,
                "cost_usd": cost_usd,
                "completion_tokens": completion_tokens,
                "prompt_tokens": prompt_tokens,
                "total_tokens": total_tokens,
                "total_api_calls": total_api_calls,
            },
            "progress": progress,
            "initial_request": initial_request,
            "final_output": final_output,
            "collected_at": self._now().isoformat(),
        }
        
        # Log extracted metrics for debugging
        self.logger.info(json.dumps({
            "event": "collected_task",
            "agent_id": agent_id,
            "task_id": task_id,
            "metrics_extracted": {
                "cost_usd": cost_usd,
                "total_api_calls": total_api_calls,
                "completion_tokens": completion_tokens,
                "prompt_tokens": prompt_tokens,
                "total_tokens": total_tokens,
                "log_count": len(logs),
                "stderr_logs_found": stderr_logs_found
            }
        }))
        return data

    def collect_all(self) -> List[Dict[str, Any]]:
        """
        Collect data for the most recent task group (3 tasks - one per agent).
        Now that each agent executes the same task independently, we evaluate each agent's
        actual performance on their assigned task.
        """
        # Get recent tasks from PostgreSQL
        tasks = self.pg.get_tasks(limit=100)
        if not tasks:
            self.logger.warning(json.dumps({"event": "no_tasks_found"}))
            return []
        
        # Group tasks by their description/title (tasks created together have same description)
        # and find the most recent group
        from collections import defaultdict
        task_groups = defaultdict(list)
        
        for task in tasks:
            # Group by description as tasks created together have identical descriptions
            description = task.get("description", "")
            task_groups[description].append(task)
        
        # Find the group with the highest task ID (most recent group)
        most_recent_group = []
        max_task_id = 0
        
        for description, group in task_groups.items():
            # Get the highest ID in this group
            group_max_id = max(int(t.get("id") or 0) for t in group)
            if group_max_id > max_task_id:
                max_task_id = group_max_id
                most_recent_group = group
        
        if not most_recent_group:
            self.logger.error(json.dumps({"event": "no_valid_task_group_found"}))
            return []
        
        self.logger.info(json.dumps({
            "event": "evaluating_task_group",
            "task_count": len(most_recent_group),
            "task_ids": [t.get("id") for t in most_recent_group],
            "agents": [t.get("agent_id") for t in most_recent_group]
        }))
        
        # Evaluate each agent's task from the most recent group
        results: List[Dict[str, Any]] = []
        
        for task in most_recent_group:
            agent_id = self._normalize_id(task.get("agent_id"))
            task_id = self._normalize_id(task.get("id"))
            
            if not agent_id or not task_id:
                continue
            
            try:
                data = self.collect_for_task(agent_id, task_id)
                results.append(data)
                self.logger.info(json.dumps({
                    "event": "collecting_agent_task",
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "status": task.get("status")
                }))
            except Exception as e:
                self.logger.error(json.dumps({
                    "event": "collect_task_error",
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "error": str(e)
                }))
        
        return results

    def collect_snapshots_for_task(self, agent_id: Optional[str], task_id: str) -> List[Dict[str, Any]]:
        """Build a series of data snapshots, one per progress update.

        For each progress row timestamp, gather Mongo logs up to that time and compute metrics.
        """
        agent_id = self._normalize_id(agent_id or self.default_agent_id)
        task_id = self._normalize_id(task_id)

        progress = self.pg.get_task_progress(task_id)
        if not progress:
            # Fallback to single snapshot
            return [self.collect_for_task(agent_id, task_id)]

        snapshots: List[Dict[str, Any]] = []
        for idx, row in enumerate(progress):
            ts = row.get("updated_at") or row.get("ts")
            # normalize ts string
            cutoff = None
            if isinstance(ts, str):
                try:
                    from datetime import datetime
                    cutoff = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except Exception:
                    cutoff = None
            else:
                cutoff = ts

            logs = self.mongo.fetch_task_logs_until(agent_id, task_id, cutoff)
            metrics = self.mongo.compute_basic_metrics(logs)

            # Extract metrics from CUA logs (stderr field contains usage statistics)
            mem_usage = 0.0
            cpu_usage = 0.0
            cost_usd = 0.0
            total_api_calls = 0
            completion_tokens = 0
            prompt_tokens = 0
            total_tokens = 0
            
            for l in logs:
                metadata = l.get("metadata", {})
                
                # Check stderr field for CUA usage statistics
                stderr = metadata.get("stderr", "")
                if stderr and isinstance(stderr, str):
                    # Extract response_cost (this is the main metric we want)
                    cost_match = re.search(r"response_cost:\s*\$?([0-9]+(?:\.[0-9]+)?)", stderr)
                    if cost_match:
                        try:
                            cost_val = float(cost_match.group(1))
                            cost_usd += cost_val  # Sum all API costs
                            total_api_calls += 1
                        except Exception:
                            pass
                    
                    # Extract token counts
                    comp_tokens_match = re.search(r"completion_tokens:\s*([0-9]+)", stderr)
                    if comp_tokens_match:
                        try:
                            completion_tokens += int(comp_tokens_match.group(1))
                        except Exception:
                            pass
                    
                    prompt_tokens_match = re.search(r"prompt_tokens:\s*([0-9]+)", stderr)
                    if prompt_tokens_match:
                        try:
                            prompt_tokens += int(prompt_tokens_match.group(1))
                        except Exception:
                            pass
                    
                    total_tokens_match = re.search(r"total_tokens:\s*([0-9]+)", stderr)
                    if total_tokens_match:
                        try:
                            total_tokens += int(total_tokens_match.group(1))
                        except Exception:
                            pass

            data = {
                "agent_id": agent_id,
                "task_id": task_id,
                "logs": logs,
                "metrics": {
                    **metrics,
                    "memory_usage_mb": mem_usage,
                    "cpu_usage_percent": cpu_usage,
                    "cost_usd": cost_usd,
                    "completion_tokens": completion_tokens,
                    "prompt_tokens": prompt_tokens,
                    "total_tokens": total_tokens,
                    "total_api_calls": total_api_calls,
                },
                # include progress up to this point
                "progress": progress[: idx + 1],
                # align snapshot timestamp with progress timestamp for plotting
                "collected_at": (ts.isoformat() if hasattr(ts, "isoformat") else str(ts)) if ts else self._now().isoformat(),
            }
            snapshots.append(data)

        self.logger.info(json.dumps({"event": "collected_task_snapshots", "agent_id": agent_id, "task_id": task_id, "count": len(snapshots)}))
        return snapshots
    
    def get_most_recent_task_for_agent(self, agent_id: str) -> Optional[str]:
        """
        Get the most recent task ID (globally, not per-agent).
        Uses PostgreSQL to get the task with the greatest ID (most recently created).
        This ensures the evaluator always evaluates the latest task, not an old task
        that happens to have recent log entries.
        
        Note: Tasks are created system-wide (not per-agent), so we get the greatest
        task ID overall. The agent_id parameter is kept for API compatibility but
        the evaluator evaluates the latest task that any agent is working on.
        """
        agent_id = self._normalize_id(agent_id)
        
        # Query PostgreSQL for the task with the greatest ID
        # This gives us the most recently created task, which is what we want to evaluate
        try:
            # Get recent tasks from PostgreSQL (limit to recent ones for efficiency)
            # Tasks are ordered by created_at DESC, so the first one has the greatest ID
            # if tasks were created in sequence
            tasks = self.pg.get_tasks(limit=100)
            if not tasks:
                self.logger.warning(json.dumps({
                    "event": "no_tasks_in_postgres",
                    "agent_id": agent_id,
                    "fallback": "using_mongo_logs"
                }))
                # Fallback to MongoDB logs if no tasks in PostgreSQL
                return self.mongo.get_most_recent_task_id(agent_id)
            
            # Get the task with the greatest ID (most recent)
            # Tasks may not be returned in ID order, so we need to check all of them
            max_task_id = max(
                (int(task.get("id") or 0) for task in tasks if task.get("id")),
                default=None
            )
            
            if max_task_id is not None:
                self.logger.info(json.dumps({
                    "event": "found_max_task_id",
                    "agent_id": agent_id,
                    "task_id": max_task_id
                }))
                return str(max_task_id)
            
            # Fallback to MongoDB logs if no valid task ID found
            self.logger.warning(json.dumps({
                "event": "no_valid_task_id_in_postgres",
                "agent_id": agent_id,
                "fallback": "using_mongo_logs"
            }))
            return self.mongo.get_most_recent_task_id(agent_id)
        except Exception as e:
            self.logger.warning(json.dumps({
                "event": "get_most_recent_task_failed",
                "agent_id": agent_id,
                "error": str(e),
                "fallback": "using_mongo_logs"
            }))
            # Fallback to MongoDB logs on error
            return self.mongo.get_most_recent_task_id(agent_id)
    
    def collect_progress_snapshots_for_agent_task(
        self,
        agent_id: str,
        task_id: str
    ) -> List[Dict[str, Any]]:
        """
        Collect progress snapshots for an agent's task using PostgreSQL progress data.
        Uses actual progress_percent values from task_progress table for accurate graphing.
        """
        agent_id = self._normalize_id(agent_id)
        task_id = self._normalize_id(task_id)
        
        self.logger.info(json.dumps({
            "event": "collect_progress_snapshots_entry",
            "agent_id": agent_id,
            "task_id": task_id
        }))
        
        # Get progress data from PostgreSQL (this has actual progress_percent values)
        try:
            task_id_int = int(task_id)
            progress_updates = self.pg.get_task_progress(task_id_int, limit=1000)
            self.logger.info(json.dumps({
                "event": "postgres_progress_fetched",
                "agent_id": agent_id,
                "task_id": task_id,
                "progress_count": len(progress_updates) if progress_updates else 0
            }))
        except (ValueError, TypeError) as e:
            self.logger.warning(json.dumps({
                "event": "postgres_progress_fetch_failed",
                "agent_id": agent_id,
                "task_id": task_id,
                "error": str(e)
            }))
            progress_updates = []
        
        # Filter progress updates to only this agent's data
        agent_progress_updates = [
            pu for pu in progress_updates 
            if pu.get("agent_id") == agent_id
        ] if progress_updates else []
        
        # Count how many progress updates have actual progress_percent values (not NULL)
        meaningful_progress_count = 0
        if agent_progress_updates:
            meaningful_progress_count = sum(
                1 for pu in agent_progress_updates 
                if pu.get("progress_percent") is not None
            )
        
        # If no progress data in PostgreSQL, OR if there are too few meaningful data points,
        # fall back to log-based approach for better granularity
        use_log_based_snapshots = (
            not agent_progress_updates or 
            meaningful_progress_count <= 3  # If only start/end or very few actual progress values
        )
        
        if use_log_based_snapshots:
            self.logger.info(json.dumps({
                "event": "using_log_based_progress_inference",
                "agent_id": agent_id,
                "task_id": task_id,
                "postgres_progress_total": len(progress_updates) if progress_updates else 0,
                "postgres_agent_progress": len(agent_progress_updates),
                "postgres_meaningful_progress": meaningful_progress_count,
                "reason": "few_meaningful_checkpoints" if agent_progress_updates else "no_postgres_data"
            }))
            # Get all logs for this task
            logs = self.mongo.fetch_task_logs(agent_id, task_id)
            
            if not logs:
                return []
            
            # Sort logs by timestamp
            sorted_logs = sorted(
                logs,
                key=lambda x: x.get("created_at") or x.get("timestamp") or datetime.min
            )
            
            snapshots = []
            cumulative_logs = []
            
            # Get known progress checkpoints from PostgreSQL if available (filtered to this agent)
            progress_checkpoints = {}
            if agent_progress_updates:
                for pu in agent_progress_updates:
                    percent = pu.get("progress_percent", 0)
                    if percent is not None:
                        progress_checkpoints[percent] = pu
            
            # Build snapshots incrementally - each log entry adds to the progress
            for idx, log in enumerate(sorted_logs):
                cumulative_logs.append(log)
                
                # Compute metrics up to this point
                metrics = self.mongo.compute_basic_metrics(cumulative_logs)
                
                # Analyze actual progress from logs using the heuristic analyzer
                # This looks at log content, error patterns, completion indicators, etc.
                inferred_progress = self._analyze_progress_from_logs(cumulative_logs)
                
                # If we have PostgreSQL checkpoints, use them as anchors/validators
                if progress_checkpoints:
                    checkpoint_percents = sorted(progress_checkpoints.keys())
                    
                    # Use checkpoints as bounds/constraints on inferred progress
                    # If we have 0% and 100% checkpoints, ensure progress stays within bounds
                    min_checkpoint = checkpoint_percents[0] if checkpoint_percents else 0
                    max_checkpoint = checkpoint_percents[-1] if checkpoint_percents else 100
                    
                    # Constrain inferred progress to checkpoint bounds
                    progress_percent = max(min_checkpoint, min(max_checkpoint, inferred_progress * 100))
                    
                    # If this is near the final logs and we have a 100% checkpoint, bias toward it
                    if idx >= len(sorted_logs) * 0.9 and max_checkpoint == 100:
                        # Gradually approach 100% in final 10% of logs
                        final_progress_ratio = (idx - len(sorted_logs) * 0.9) / (len(sorted_logs) * 0.1)
                        progress_percent = max(progress_percent, 90 + final_progress_ratio * 10)
                else:
                    # No checkpoints - use pure analysis
                    progress_percent = inferred_progress * 100
                
                # Extract metrics from CUA logs (stderr field contains usage statistics)
                mem_usage = 0.0
                cpu_usage = 0.0
                cost_usd = 0.0
                total_api_calls = 0
                completion_tokens = 0
                prompt_tokens = 0
                total_tokens = 0
                
                for l in cumulative_logs:
                    metadata = l.get("metadata", {})
                    
                    # Check stderr field for CUA usage statistics
                    stderr = metadata.get("stderr", "")
                    if stderr and isinstance(stderr, str):
                        # Extract response_cost (this is the main metric we want)
                        cost_match = re.search(r"response_cost:\s*\$?([0-9]+(?:\.[0-9]+)?)", stderr)
                        if cost_match:
                            try:
                                cost_val = float(cost_match.group(1))
                                cost_usd += cost_val  # Sum all API costs
                                total_api_calls += 1
                            except Exception:
                                pass
                        
                        # Extract token counts
                        comp_tokens_match = re.search(r"completion_tokens:\s*([0-9]+)", stderr)
                        if comp_tokens_match:
                            try:
                                completion_tokens += int(comp_tokens_match.group(1))
                            except Exception:
                                pass
                        
                        prompt_tokens_match = re.search(r"prompt_tokens:\s*([0-9]+)", stderr)
                        if prompt_tokens_match:
                            try:
                                prompt_tokens += int(prompt_tokens_match.group(1))
                            except Exception:
                                pass
                        
                        total_tokens_match = re.search(r"total_tokens:\s*([0-9]+)", stderr)
                        if total_tokens_match:
                            try:
                                total_tokens += int(total_tokens_match.group(1))
                            except Exception:
                                pass
                
                timestamp = log.get("created_at") or log.get("timestamp")
                if isinstance(timestamp, str):
                    try:
                        timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    except:
                        timestamp = self._now()
                elif not timestamp:
                    timestamp = self._now()
                
                snapshot = {
                    "agent_id": agent_id,
                    "task_id": task_id,
                    "logs": cumulative_logs.copy(),
                    "metrics": {
                        **metrics,
                        "memory_usage_mb": mem_usage,
                        "cpu_usage_percent": cpu_usage,
                        "cost_usd": cost_usd,
                        "completion_tokens": completion_tokens,
                        "prompt_tokens": prompt_tokens,
                        "total_tokens": total_tokens,
                        "total_api_calls": total_api_calls,
                    },
                    "progress_percent": progress_percent,
                    "collected_at": timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp),
                    "step": idx + 1
                }
                snapshots.append(snapshot)
            
            snapshots = self._ensure_completion_if_stalled(snapshots, task_id)
            
            # Log progress distribution for analysis
            progress_values = [s.get("progress_percent", 0) for s in snapshots]
            self.logger.info(json.dumps({
                "event": "created_log_based_snapshots",
                "agent_id": agent_id,
                "task_id": task_id,
                "snapshot_count": len(snapshots),
                "log_count": len(logs),
                "used_postgres_checkpoints": bool(progress_checkpoints),
                "progress_range": f"{min(progress_values):.1f}% - {max(progress_values):.1f}%",
                "progress_method": "evaluator_analysis"
            }))
            return snapshots
        
        # Use PostgreSQL progress data (preferred method)
        # Sort progress updates by timestamp (ascending for chronological order)
        progress_updates_sorted = sorted(
            progress_updates,
            key=lambda x: x.get("timestamp") or datetime.min
        )
        
        # Get all MongoDB logs for this task to use their timestamps
        all_logs = self.mongo.fetch_task_logs(agent_id, task_id)
        # Sort logs by timestamp
        sorted_logs = sorted(
            all_logs,
            key=lambda x: x.get("created_at") or x.get("timestamp") or datetime.min
        )
        
        snapshots = []
        log_idx = 0  # Track position in logs
        
        for idx, progress_row in enumerate(progress_updates_sorted):
            # Get timestamp for this progress update (for cutoff)
            ts = progress_row.get("timestamp")
            if isinstance(ts, str):
                try:
                    cutoff = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                except:
                    cutoff = None
            else:
                cutoff = ts
            
            # Get logs up to this progress point
            if cutoff:
                logs = self.mongo.fetch_task_logs_until(agent_id, task_id, cutoff)
            else:
                logs = self.mongo.fetch_task_logs(agent_id, task_id)
            
            # Compute metrics from logs
            metrics = self.mongo.compute_basic_metrics(logs)
            
            # Extract metrics from CUA logs (stderr field contains usage statistics)
            mem_usage = 0.0
            cpu_usage = 0.0
            cost_usd = 0.0
            total_api_calls = 0
            completion_tokens = 0
            prompt_tokens = 0
            total_tokens = 0
            
            for l in logs:
                metadata = l.get("metadata", {})
                
                # Check stderr field for CUA usage statistics
                stderr = metadata.get("stderr", "")
                if stderr and isinstance(stderr, str):
                    # Extract response_cost (this is the main metric we want)
                    cost_match = re.search(r"response_cost:\s*\$?([0-9]+(?:\.[0-9]+)?)", stderr)
                    if cost_match:
                        try:
                            cost_val = float(cost_match.group(1))
                            cost_usd += cost_val  # Sum all API costs
                            total_api_calls += 1
                        except Exception:
                            pass
                    
                    # Extract token counts
                    comp_tokens_match = re.search(r"completion_tokens:\s*([0-9]+)", stderr)
                    if comp_tokens_match:
                        try:
                            completion_tokens += int(comp_tokens_match.group(1))
                        except Exception:
                            pass
                    
                    prompt_tokens_match = re.search(r"prompt_tokens:\s*([0-9]+)", stderr)
                    if prompt_tokens_match:
                        try:
                            prompt_tokens += int(prompt_tokens_match.group(1))
                        except Exception:
                            pass
                    
                    total_tokens_match = re.search(r"total_tokens:\s*([0-9]+)", stderr)
                    if total_tokens_match:
                        try:
                            total_tokens += int(total_tokens_match.group(1))
                        except Exception:
                            pass
            
            # Use actual progress_percent from PostgreSQL
            progress_percent = progress_row.get("progress_percent", 0.0)
            if isinstance(progress_percent, (int, float)):
                # Ensure it's in 0-100 range
                if progress_percent <= 1.0:
                    progress_percent = progress_percent * 100.0
                progress_percent = max(0.0, min(100.0, float(progress_percent)))
            else:
                progress_percent = 0.0
            
            # Use MongoDB log timestamp for this snapshot (more granular than PostgreSQL)
            # Find the most recent log entry up to this point
            timestamp = None
            if logs:
                # Use the latest log's timestamp
                latest_log = logs[-1] if logs else None
                if latest_log:
                    log_ts = latest_log.get("created_at") or latest_log.get("timestamp")
                    if log_ts:
                        if isinstance(log_ts, str):
                            try:
                                timestamp = datetime.fromisoformat(log_ts.replace('Z', '+00:00'))
                            except:
                                pass
                        elif isinstance(log_ts, datetime):
                            timestamp = log_ts
            
            # Fallback to PostgreSQL timestamp if no log timestamp found
            if not timestamp:
                if isinstance(ts, str):
                    try:
                        timestamp = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    except:
                        timestamp = self._now()
                elif ts:
                    timestamp = ts if isinstance(ts, datetime) else self._now()
                else:
                    timestamp = self._now()
            
            # Ensure timestamp is unique (add small offset if needed)
            # This prevents vertical lines when multiple progress updates have same timestamp
            if idx > 0:
                prev_timestamp = snapshots[-1].get("collected_at")
                if isinstance(prev_timestamp, str):
                    try:
                        prev_ts = datetime.fromisoformat(prev_timestamp.replace('Z', '+00:00'))
                    except:
                        prev_ts = None
                else:
                    prev_ts = prev_timestamp
                
                if prev_ts and timestamp <= prev_ts:
                    # Add small offset to ensure chronological order
                    from datetime import timedelta
                    timestamp = prev_ts + timedelta(milliseconds=100)
            
            snapshot = {
                "agent_id": agent_id,
                "task_id": task_id,
                "logs": logs,
                "metrics": {
                    **metrics,
                    "memory_usage_mb": mem_usage,
                    "cpu_usage_percent": cpu_usage,
                    "cost_usd": cost_usd,
                    "completion_tokens": completion_tokens,
                    "prompt_tokens": prompt_tokens,
                    "total_tokens": total_tokens,
                    "total_api_calls": total_api_calls,
                },
                "progress_percent": progress_percent,  # Use actual PostgreSQL value
                "collected_at": timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp),
                "step": idx + 1
            }
            snapshots.append(snapshot)
        
        snapshots = self._ensure_completion_if_stalled(snapshots, task_id)
        return snapshots
    
    def _analyze_progress_from_logs(self, logs: List[Dict[str, Any]]) -> float:
        """
        Analyze progress from log messages using multiple heuristics.
        Returns a value between 0.0 and 1.0 representing estimated progress.
        
        This evaluates:
        - Explicit progress indicators in logs
        - Task completion keywords
        - Error patterns (reduce progress)
        - Activity patterns (actions taken)
        - Tool/API usage patterns
        """
        if not logs:
            return 0.0
        
        import re
        
        max_explicit_progress = 0.0
        activity_score = 0.0
        completion_signals = 0
        error_count = 0
        action_count = 0
        
        # Patterns for explicit progress
        progress_patterns = [
            r"progress[:\s]+(\d+(?:\.\d+)?)\s*%",
            r"(\d+(?:\.\d+)?)\s*%\s*complete",
            r"completed[:\s]+(\d+(?:\.\d+)?)\s*%",
        ]
        
        # Patterns for steps/phases
        step_pattern = r"step\s+(\d+)(?:\s+of\s+(\d+))?|phase\s+(\d+)(?:\s+of\s+(\d+))?"
        
        # Completion indicators
        completion_words = ["completed", "done", "finished", "success", "succeeded", "accomplished"]
        error_words = ["error", "failed", "failure", "exception", "crashed"]
        action_words = ["executing", "running", "processing", "starting", "opening", "created", "saved", "sent"]
        
        total_steps = None
        current_step = 0
        
        for log in logs:
            message = str(log.get("message", "")).lower()
            level = str(log.get("level", "")).lower()
            
            # Check for explicit progress percentages
            for pattern in progress_patterns:
                matches = re.findall(pattern, message, re.IGNORECASE)
                if matches:
                    try:
                        if isinstance(matches[0], tuple):
                            val = float(matches[0][0]) if matches[0][0] else 0
                        else:
                            val = float(matches[0])
                        # Normalize to 0-1
                        progress_val = val / 100.0 if val > 1.0 else val
                        max_explicit_progress = max(max_explicit_progress, min(1.0, progress_val))
                    except (ValueError, IndexError):
                        pass
            
            # Check for step/phase progress
            step_matches = re.search(step_pattern, message, re.IGNORECASE)
            if step_matches:
                groups = [g for g in step_matches.groups() if g]
                if len(groups) >= 1:
                    try:
                        current_step = max(current_step, int(groups[0]))
                        if len(groups) >= 2:
                            total_steps = int(groups[1])
                    except (ValueError, IndexError):
                        pass
            
            # Count completion signals
            if level == "info" and any(word in message for word in completion_words):
                completion_signals += 1
            
            # Count errors
            if level in ["error", "warning"] or any(word in message for word in error_words):
                error_count += 1
            
            # Count actions (indicates work being done)
            if any(word in message for word in action_words):
                action_count += 1
        
        # Calculate step-based progress if we have step information
        step_progress = 0.0
        if total_steps and current_step:
            step_progress = min(1.0, current_step / total_steps)
        elif current_step > 0:
            # No total, but we have current step - estimate based on reasonable task length
            step_progress = min(0.9, current_step * 0.15)  # Assume ~6-7 steps
        
        # Activity-based progress (how much work has been done)
        # More actions = more progress, but cap it
        activity_progress = min(0.85, action_count * 0.08)  # Each action ~ 8% progress, cap at 85%
        
        # Completion-based progress
        completion_progress = 0.0
        if completion_signals > 0:
            # Strong completion signals suggest near or at completion
            completion_progress = min(1.0, 0.7 + (completion_signals * 0.1))
        
        # Error penalty - errors suggest less progress or setbacks
        error_penalty = min(0.3, error_count * 0.05)  # Max 30% penalty
        
        # Combine all signals - take the maximum of explicit indicators
        # and use activity/steps as supporting evidence
        progress = max(
            max_explicit_progress,  # Trust explicit progress most
            step_progress,  # Step-based is good indicator
            completion_progress if completion_signals > 0 else 0,  # Completion is strong signal
            activity_progress * 0.7  # Activity alone is weaker signal
        )
        
        # Apply error penalty
        progress = max(0.0, progress - error_penalty)
        
        # If we have very few logs and no clear progress, give minimal credit
        if progress == 0.0 and len(logs) > 0:
            # Basic progress just for having activity
            progress = min(0.15, len(logs) * 0.02)
        
        return max(0.0, min(1.0, progress))

    def _is_task_completed_in_pg(self, task_id: str) -> bool:
        try:
            task_id_int = int(task_id)
            task = self.pg.get_task(task_id_int)
            if task and str(task.get("status", "")).lower() == "completed":
                return True
        except Exception:
            pass
        return False

    def _ensure_completion_if_stalled(self, snapshots: List[Dict[str, Any]], task_id: str) -> List[Dict[str, Any]]:
        """
        Detects if progress is plateaued for 3+ consecutive points while the task is completed.
        If so, forces the next point to 100 (or appends a synthetic final point).
        """
        if not snapshots:
            return snapshots
        
        def is_close(a: float, b: float, tol: float = 1e-3) -> bool:
            return abs(a - b) <= tol
        
        consecutive = 1
        last_value = snapshots[0].get("progress_percent") or 0.0
        
        for idx in range(1, len(snapshots)):
            value = snapshots[idx].get("progress_percent") or 0.0
            if is_close(value, last_value):
                consecutive += 1
            else:
                consecutive = 1
                last_value = value
                continue
            
            last_value = value
            if consecutive >= 3 and value < 1.0:
                if self._is_task_completed_in_pg(task_id):
                    # Update next point if exists, otherwise append new point
                    if idx + 1 < len(snapshots):
                        snapshots[idx + 1]["progress_percent"] = 1.0
                    else:
                        final_snapshot = snapshots[-1].copy()
                        final_snapshot["progress_percent"] = 1.0
                        final_snapshot["collected_at"] = self._now().isoformat()
                        final_snapshot["step"] = (final_snapshot.get("step") or len(snapshots)) + 1
                        snapshots.append(final_snapshot)
                    break
        
        # Also ensure final point reaches 1.0 if task completed and last progress < 1
        last_progress = snapshots[-1].get("progress_percent") or 0.0
        if last_progress < 1.0 and self._is_task_completed_in_pg(task_id):
            snapshots[-1]["progress_percent"] = 1.0
        
        return snapshots
