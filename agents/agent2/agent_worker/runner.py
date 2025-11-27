# Agent runner: orchestrates task polling, execution, and progress tracking
"""Agent runner that polls for tasks and executes them using execute_task.py."""

import os
import subprocess
import time
import threading
import shutil
from pathlib import Path
from typing import Optional
from datetime import datetime
from uuid import uuid4

from agent_worker.config import Config
from agent_worker.db_adapters import PostgresClient, MongoClientWrapper


# Removed: list_new_screenshots - CUA trajectory processor handles screenshots


class AgentRunner:
    """Agent runner that polls for tasks and executes them."""
    
    def __init__(
        self,
        config: Config,
        postgres_client: PostgresClient,
        mongo_client: MongoClientWrapper
    ):
        """
        Initialize agent runner.
        
        Args:
            config: Configuration object
            postgres_client: PostgreSQL client
            mongo_client: MongoDB client
        """
        self.config = config
        self.postgres = postgres_client
        self.mongo = mongo_client
        self.running = False
        self.current_workdir: Optional[str] = None
    
    def poll_loop(self):
        """Main polling loop that runs indefinitely."""
        self.running = True
        self.mongo.write_log(
            task_id=None,
            level="info",
            message=f"Agent worker started (agent_id={self.config.agent_id})"
        )
        print(f"[{self.config.agent_id}] Agent worker started")
        
        while self.running:
            try:
                # Poll for current task
                task = self.postgres.get_current_task(self.config.agent_id)
                
                if not task:
                    # No task available, sleep and continue
                    print(f"[{self.config.agent_id}] No task found, polling again in {self.config.poll_interval_seconds}s...")
                    time.sleep(self.config.poll_interval_seconds)
                    continue
                
                task_id = task["id"]
                
                # Check progress
                progress = self.postgres.get_task_progress_max_percent(task_id)
                
                if progress >= 100:
                    # Task already completed, skip
                    time.sleep(self.config.poll_interval_seconds)
                    continue
                
                # Task found and not completed, execute it
                self._execute_task(task)
                
            except Exception as e:
                # Log error and continue polling
                error_msg = f"Error in poll loop: {str(e)}"
                print(f"[{self.config.agent_id}] ERROR: {error_msg}")
                self.mongo.write_log(
                    task_id=None,
                    level="error",
                    message=error_msg,
                    meta={"exc_info": str(e)}
                )
                time.sleep(self.config.poll_interval_seconds)
        
        self.mongo.write_log(
            task_id=None,
            level="info",
            message="Agent worker stopped"
        )
        print(f"[{self.config.agent_id}] Agent worker stopped")
    
    def _execute_task(self, task: dict):
        """
        Execute a task using execute_task.py.
        
        Args:
            task: Task dictionary from database
        """
        task_id = task["id"]
        workdir = None
        original_cwd = os.getcwd()  # Save original working directory early
        
        try:
            # Create unique working directory
            # Use readable timestamp format: YYYY-MM-DD_HH-MM-SS
            timestamp = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
            workdir = f"/tmp/agent_work/{self.config.agent_id}/{task_id}/{timestamp}"
            workdir_path = Path(workdir)
            workdir_path.mkdir(parents=True, exist_ok=True)
            self.current_workdir = workdir
            
            # Create screenshots directory
            screenshots_dir = workdir_path / "screenshots"
            screenshots_dir.mkdir(exist_ok=True)
            
            # Log task picked
            description_preview = task.get("description", "")[:50] if task.get("description") else "No description"
            self.mongo.write_log(
                task_id=task_id,
                level="debug",
                message=f"Task picked: {task.get('title', 'Unknown')}",
                meta={"task_id": task_id, "title": task.get("title")}
            )
            print(f"[{self.config.agent_id}] Task {task_id} picked: {task.get('title', 'Unknown')}")
            print(f"[{self.config.agent_id}] Description: {description_preview}...")
            
            # Insert initial progress
            self.postgres.insert_progress(
                task_id=task_id,
                agent_id=self.config.agent_id,
                percent=0,
                message="Task started"
            )
            
            # Start heartbeat thread for progress updates
            heartbeat_stop = threading.Event()
            heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop,
                args=(task_id, heartbeat_stop),
                daemon=True
            )
            heartbeat_thread.start()
            
            # Get task description
            task_description = task.get("description", "") or task.get("title", "")
            if not task_description:
                task_description = f"Task {task_id}"
            
            # Execute task using execute_task.py script
            execute_task_script = Path(__file__).parent / "execute_task.py"
            if not execute_task_script.exists():
                error_msg = f"execute_task.py not found at {execute_task_script}"
                print(f"[{self.config.agent_id}] ERROR: {error_msg}")
                self.mongo.write_log(task_id=task_id, level="error", message=error_msg)
                self.postgres.insert_progress(task_id=task_id, agent_id=self.config.agent_id, percent=0, message=error_msg)
                return
            
            start_time = time.time()
            try:
                # Pass task description and MongoDB connection info as environment variables
                env = os.environ.copy()
                env["TASK_DESCRIPTION"] = task_description
                env["TASK_ID"] = str(task_id)
                env["MONGO_URI"] = self.config.mongo_uri
                env["AGENT_ID"] = self.config.agent_id
                env["WORKDIR"] = str(workdir_path)
                print(f"[{self.config.agent_id}] Executing task {task_id} with env: TASK_ID={task_id}, WORKDIR={workdir_path}")
                
                # Use Popen to stream output
                process = subprocess.Popen(
                    ["python", "-u", str(execute_task_script), task_description],
                    cwd=str(workdir_path),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env,
                    bufsize=1,
                    universal_newlines=True
                )
                
                stdout_lines = []
                stderr_lines = []
                
                # Function to consume stderr in a separate thread
                def consume_stderr(stream, accumulator):
                    for line in stream:
                        accumulator.append(line)
                
                stderr_thread = threading.Thread(target=consume_stderr, args=(process.stderr, stderr_lines))
                stderr_thread.daemon = True
                stderr_thread.start()
                
                # Read stdout in main thread
                while True:
                    # Check timeout
                    if self.config.run_task_timeout_seconds and time.time() - start_time > self.config.run_task_timeout_seconds:
                        print(f"[{self.config.agent_id}] Task {task_id} timed out, killing process...")
                        process.kill()
                        # Wait for thread to finish to avoid zombie issues, though kill is drastic
                        break 
                    
                    # Use readline to get line-by-line output
                    line = process.stdout.readline()
                    if not line and process.poll() is not None:
                        break
                        
                    if line:
                        stdout_lines.append(line)
                        
                        # Check for agent messages to stream to user
                        if "Agent: " in line:
                            try:
                                msg = line.split("Agent: ", 1)[1].strip()
                                if msg:
                                    self.postgres.insert_progress(
                                        task_id=task_id,
                                        agent_id=self.config.agent_id,
                                        percent=None,
                                        message=msg
                                    )
                            except Exception as e:
                                print(f"[{self.config.agent_id}] Warning: Failed to stream agent message: {e}")
                
                # Handle timeout explicitly if loop broke due to timeout
                if self.config.run_task_timeout_seconds and time.time() - start_time > self.config.run_task_timeout_seconds:
                     raise subprocess.TimeoutExpired(process.args, self.config.run_task_timeout_seconds)

                process.wait()
                stderr_thread.join(timeout=5)
                
                end_time = time.time()
                duration = end_time - start_time
                
                # Stop heartbeat
                heartbeat_stop.set()
                heartbeat_thread.join(timeout=1)
                
                # Get stdout and stderr
                stdout = "".join(stdout_lines)
                stderr = "".join(stderr_lines)
                return_code = process.returncode
                
                # Log execution result
                self.mongo.write_log(
                    task_id=task_id,
                    level="info" if return_code == 0 else "error",
                    message=f"execute_task.py completed (return_code={return_code}, duration={duration:.2f}s)",
                    meta={
                        "return_code": return_code,
                        "duration": duration,
                        "stdout_length": len(stdout),
                        "stderr_length": len(stderr)
                    }
                )
                
                # Write full stdout/stderr to logs
                if stdout:
                    self.mongo.write_log(
                        task_id=task_id,
                        level="debug",
                        message="execute_task.py stdout",
                        meta={"stdout": stdout}
                    )
                if stderr:
                    self.mongo.write_log(
                        task_id=task_id,
                        level="debug",
                        message="execute_task.py stderr",
                        meta={"stderr": stderr}
                    )
                
                # Determine final progress percent based on return code
                if return_code == 0:
                    final_percent = 100
                else:
                    final_percent = 0
                
                # Insert final progress
                self.postgres.insert_progress(
                    task_id=task_id,
                    agent_id=self.config.agent_id,
                    percent=final_percent,
                    message=f"completed (return_code={return_code})"
                )
                
                # Update task response
                # Extract agent response from stdout (between AGENT_RESPONSE_START and AGENT_RESPONSE_END markers)
                response_text = ""
                if "AGENT_RESPONSE_START" in stdout and "AGENT_RESPONSE_END" in stdout:
                    # Extract response between markers
                    start_idx = stdout.find("AGENT_RESPONSE_START")
                    end_idx = stdout.find("AGENT_RESPONSE_END")
                    if start_idx != -1 and end_idx != -1:
                        # Get content between markers
                        response_section = stdout[start_idx:end_idx]
                        # Extract lines between the markers (skip the marker lines themselves)
                        lines = response_section.split('\n')
                        response_lines = []
                        in_response = False
                        separator = "=" * 60
                        for line in lines:
                            if "AGENT_RESPONSE_START" in line or separator in line:
                                in_response = True
                                continue
                            if "AGENT_RESPONSE_END" in line:
                                break
                            if in_response and line.strip() and separator not in line:
                                response_lines.append(line)
                        response_text = '\n'.join(response_lines).strip()
                
                # Fallback: use entire stdout if markers not found
                if not response_text:
                    response_text = stdout.strip()
                
                # Final fallback: use summary if stdout is empty
                if not response_text:
                    response_text = f"Task completed (return_code={return_code}, duration={duration:.2f}s)"
                
                # Update task status to completed
                try:
                    self.postgres.update_task_status(
                        task_id=task_id,
                        status="completed" if return_code == 0 else "failed",
                        metadata={"completed_at": datetime.utcnow().isoformat(), "return_code": return_code}
                    )
                except Exception as e:
                    print(f"[{self.config.agent_id}] Warning: Failed to update task status: {e}")
                
                # Update task response (wrap in try/except to handle transaction errors gracefully)
                try:
                    self.postgres.update_task_response(
                        task_id=task_id,
                        agent_id=self.config.agent_id,
                        response_text=response_text
                    )
                except Exception as e:
                    # Log error but don't fail the task execution
                    print(f"[{self.config.agent_id}] Warning: Failed to update task response: {e}")
                    self.mongo.write_log(
                        task_id=task_id,
                        level="warning",
                        message=f"Failed to update task response: {str(e)}"
                    )
                
                # Write agent response to MongoDB for chat display
                # Only log if return_code is non-zero (error)
                # If success (0), the agent/trajectory processor handles logging to avoid duplicates
                if response_text and response_text.strip() and return_code != 0:
                    try:
                        self.mongo.write_log(
                            task_id=task_id,
                            level="info",
                            message=response_text,
                            meta={"source": "agent_output", "type": "agent_response"}
                        )
                    except Exception as e:
                        print(f"[{self.config.agent_id}] Warning: Failed to log agent response to MongoDB: {e}")
                
                # Insert final 100% progress if not already
                if final_percent < 100:
                    self.postgres.insert_progress(
                        task_id=task_id,
                        agent_id=self.config.agent_id,
                        percent=100,
                        message="completed"
                    )
                
                print(f"[{self.config.agent_id}] Task {task_id} completed (return_code={return_code})")
                
            except subprocess.TimeoutExpired:
                # Task timed out
                heartbeat_stop.set()
                heartbeat_thread.join(timeout=1)
                
                error_msg = f"execute_task.py timed out after {self.config.run_task_timeout_seconds} seconds"
                print(f"[{self.config.agent_id}] ERROR: {error_msg}")
                self.mongo.write_log(
                    task_id=task_id,
                    level="error",
                    message=error_msg
                )
                
                self.postgres.insert_progress(
                    task_id=task_id,
                    agent_id=self.config.agent_id,
                    percent=0,
                    message=error_msg
                )
                
                # Update task status to failed
                try:
                    self.postgres.update_task_status(
                        task_id=task_id,
                        status="failed",
                        metadata={"failed_at": datetime.utcnow().isoformat(), "error": error_msg}
                    )
                except Exception as e:
                    print(f"[{self.config.agent_id}] Warning: Failed to update task status: {e}")
                
                # Update task response (wrap in try/except to handle transaction errors gracefully)
                try:
                    self.postgres.update_task_response(
                        task_id=task_id,
                        agent_id=self.config.agent_id,
                        response_text=error_msg
                    )
                except Exception as e:
                    # Log error but don't fail the task execution
                    print(f"[{self.config.agent_id}] Warning: Failed to update task response: {e}")
            
            finally:
                # Restore original working directory
                try:
                    os.chdir(original_cwd)
                except:
                    pass
        
        except Exception as e:
            # Log error
            error_msg = f"Error executing task {task_id}: {str(e)}"
            print(f"[{self.config.agent_id}] ERROR: {error_msg}")
            self.mongo.write_log(
                task_id=task_id,
                level="error",
                message=error_msg,
                meta={"exc_info": str(e)}
            )
            
            # Insert error progress
            try:
                self.postgres.insert_progress(
                    task_id=task_id,
                    agent_id=self.config.agent_id,
                    percent=0,
                    message=error_msg
                )
            except:
                pass
            
            # Update task status to failed
            try:
                self.postgres.update_task_status(
                    task_id=task_id,
                    status="failed",
                    metadata={"failed_at": datetime.utcnow().isoformat(), "error": error_msg}
                )
            except:
                pass
        
        finally:
            # Cleanup workdir
            if workdir and os.path.exists(workdir):
                try:
                    shutil.rmtree(workdir)
                except Exception as e:
                    print(f"[{self.config.agent_id}] Warning: Failed to cleanup workdir {workdir}: {e}")
            self.current_workdir = None
    
    def _heartbeat_loop(self, task_id: int, stop_event: threading.Event):
        """
        Heartbeat loop that writes progress updates while task is running.
        
        Args:
            task_id: Task identifier
            stop_event: Event to stop the heartbeat
        """
        while not stop_event.is_set():
            try:
                self.postgres.insert_progress(
                    task_id=task_id,
                    agent_id=self.config.agent_id,
                    percent=None,
                    message="working..."
                )
            except:
                pass  # Ignore errors in heartbeat
            
            # Sleep for poll interval, or until stop event
            if stop_event.wait(self.config.poll_interval_seconds):
                break
    
    def stop(self):
        """Stop the polling loop gracefully."""
        self.running = False

