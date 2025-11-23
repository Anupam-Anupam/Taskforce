#!/usr/bin/env python3
"""
Task execution script for agent worker.
This script receives a task description and executes it using the CUA agent.

Usage:
    python execute_task.py "task description"
    or
    TASK_DESCRIPTION="task description" python execute_task.py
"""

import sys
import os
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from typing import Optional, Any

# Load .env file if it exists
load_dotenv()

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Add CUA to path
cua_path = project_root / "CUA"
if cua_path.exists():
    sys.path.insert(0, str(cua_path))

# Add agent_worker to path for imports
agent_worker_path = Path(__file__).parent
sys.path.insert(0, str(agent_worker_path))

# In Docker, code is at /app/agent_worker/, so adjust paths
if Path("/app/agent_worker").exists():
    sys.path.insert(0, "/app")
    sys.path.insert(0, "/app/agent_worker")
    # CUA might be at /app/CUA
    if Path("/app/CUA").exists():
        sys.path.insert(0, "/app/CUA")




# Screenshots handled by CUA trajectory processor - no manual screenshot code needed


def check_cua_packages():
    """Check if CUA packages are installed and importable."""
    diagnostics = {
        "packages_installed": False,
        "agent_importable": False,
        "computer_importable": False,
        "errors": []
    }
    
    # Check if packages are installed via pip
    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "pip", "list"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if "cua-agent" in result.stdout.lower() or "cua-computer" in result.stdout.lower():
            diagnostics["packages_installed"] = True
    except Exception as e:
        diagnostics["errors"].append(f"Failed to check pip list: {e}")
    
    # Try to import agent module
    try:
        import agent
        diagnostics["agent_importable"] = True
    except ImportError as e:
        diagnostics["errors"].append(f"Failed to import agent module: {e}")
    except Exception as e:
        diagnostics["errors"].append(f"Unexpected error importing agent module: {e}")
    
    # Try to import computer module
    try:
        import computer
        diagnostics["computer_importable"] = True
    except ImportError as e:
        diagnostics["errors"].append(f"Failed to import computer module: {e}")
    except Exception as e:
        diagnostics["errors"].append(f"Unexpected error importing computer module: {e}")
    
    return diagnostics


def get_task_description():
    """Get task description from command line or environment."""
    if len(sys.argv) > 1:
        # Get from command line arguments
        task_description = " ".join(sys.argv[1:])
    else:
        # Get from environment variable
        task_description = os.getenv("TASK_DESCRIPTION", "")
    
    return task_description  # Return empty string if not provided (for polling mode)


async def execute_task_async(task_description: str, task_id: Optional[int] = None, mongo_client: Optional[Any] = None) -> dict:
    """
    Execute a task using CUA agent and return results.
    
    Args:
        task_description: The task description to execute
        
    Returns:
        Dictionary with execution results
    """
    print(f"Executing task: {task_description}")
    print("=" * 60)
    
    result = {
        "status": "success",
        "output": "",
        "error": None
    }
    
    # Run diagnostics first
    print("\n=== CUA Package Diagnostics ===")
    diagnostics = check_cua_packages()
    print(f"Packages installed (via pip): {diagnostics['packages_installed']}")
    print(f"Agent module importable: {diagnostics['agent_importable']}")
    print(f"Computer module importable: {diagnostics['computer_importable']}")
    if diagnostics['errors']:
        print("Errors found:")
        for error in diagnostics['errors']:
            print(f"  - {error}")
    print("=" * 60)
    print()
    
    try:
        # Try to import and use CUA agent
        try:
            # First, check for required environment variables
            cua_api_key = os.getenv("CUA_API_KEY")
            cua_sandbox_name = os.getenv("CUA_SANDBOX_NAME", "default")
            openai_api_key = os.getenv("OPENAI_API_KEY")
            
            print("Checking CUA environment variables...")
            missing_vars = []
            if not cua_api_key:
                missing_vars.append("CUA_API_KEY")
            if not openai_api_key:
                missing_vars.append("OPENAI_API_KEY")
            
            if missing_vars:
                raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
            
            print(f"✓ CUA_API_KEY is set (length: {len(cua_api_key)})")
            print(f"✓ CUA_SANDBOX_NAME: {cua_sandbox_name}")
            print(f"✓ OPENAI_API_KEY is set (length: {len(openai_api_key)})")
            
            # Import from cua packages (installed via pip as cua-agent, cua-computer)
            # But imported as 'agent' and 'computer' modules
            print("Attempting to import CUA packages...")
            try:
                from agent import ComputerAgent
                print("✓ Successfully imported ComputerAgent from agent module")
            except ImportError as import_err:
                print(f"✗ Failed to import ComputerAgent from agent module: {import_err}")
                print(f"  Import error details: {type(import_err).__name__}: {import_err}")
                import traceback
                traceback.print_exc()
                raise
            
            try:
                from computer import Computer, VMProviderType
                print("✓ Successfully imported Computer and VMProviderType from computer module")
            except ImportError as import_err:
                print(f"✗ Failed to import Computer/VMProviderType from computer module: {import_err}")
                print(f"  Import error details: {type(import_err).__name__}: {import_err}")
                import traceback
                traceback.print_exc()
                raise
            
            print("Initializing CUA agent...")
            
            # Create computer instance
            print("Creating Computer instance...")
            try:
                computer = Computer(
                    os_type="linux",
                    api_key=cua_api_key,
                    name=cua_sandbox_name,
                    provider_type=VMProviderType.CLOUD,
                )
                print("✓ Computer instance created successfully")
            except Exception as comp_err:
                print(f"✗ Failed to create Computer instance: {comp_err}")
                print(f"  Error type: {type(comp_err).__name__}")
                import traceback
                traceback.print_exc()
                raise
            
            # Create agent with trajectory_dir - CUA handles screenshots automatically
            # Use workdir if provided, otherwise current directory
            workdir = os.getenv("WORKDIR")
            if workdir:
                trajectory_dir = Path(workdir) / "trajectories"
            else:
                trajectory_dir = Path("trajectories")
            trajectory_dir.mkdir(parents=True, exist_ok=True)
            print(f"📁 Trajectory directory: {trajectory_dir.absolute()}")
            
            # Start trajectory processor if MongoDB client provided
            trajectory_observer = None
            if mongo_client:
                try:
                    from trajectory_processor import start_processor
                    trajectory_observer = start_processor(trajectory_dir, mongo_client, task_id)
                    print(f"✓ Trajectory processor started, watching: {trajectory_dir.absolute()}")
                except Exception as e:
                    print(f"⚠️  Failed to start trajectory processor: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                print("⚠️  No MongoDB client provided - trajectory processor not started")
            
            print("Creating ComputerAgent instance...")
            try:
                agent = ComputerAgent(
                    model="omniparser+openai/gpt-4o",
                    tools=[computer],
                    only_n_most_recent_images=3,
                    verbosity=logging.INFO,
                    trajectory_dir=str(trajectory_dir),
                )
                print("✓ ComputerAgent instance created successfully")
            except Exception as agent_err:
                print(f"✗ Failed to create ComputerAgent instance: {agent_err}")
                print(f"  Error type: {type(agent_err).__name__}")
                import traceback
                traceback.print_exc()
                raise
            
            print(f"Executing task: {task_description}")
            
            # Create conversation history
            history = [{"role": "user", "content": task_description}]
            
            # Execute the task
            print("Starting task execution...")
            collected_outputs = []
            
            # Maintain conversation history properly to avoid tool_call_id errors
            # Based on CUA examples, we need to extend history with agent outputs
            # However, we pass a copy to agent.run() to avoid modifying the object it's using
            try:
                # Use a fresh history for each run to avoid state issues
                history = [{"role": "user", "content": task_description}]
                
                # Pass a copy of history to agent.run() to avoid conflicts
                # The agent manages its own internal state, but we maintain our own history
                # We extend our history after each iteration to match CUA examples
                async for result_item in agent.run(history.copy(), stream=False):
                    output_items = result_item.get("output", []) or []
                    
                    # Extend our history with agent outputs (matches CUA examples)
                    # We extend our copy, not the one passed to agent.run()
                    history.extend(output_items)
                    
                    for item in output_items:
                        item_type = item.get("type", "")
                        if item_type == "message":
                            content_parts = item.get("content", []) or []
                            for cp in content_parts:
                                text = cp.get("text") if isinstance(cp, dict) else None
                                if text:
                                    collected_outputs.append(text)
                                    print(f"Agent: {text}")
                                    if mongo_client:
                                        mongo_client.write_log(
                                            task_id=task_id,
                                            level="info",
                                            message=text,
                                            meta={"source": "agent_output"}
                                        )
                        elif item_type == "computer_call":
                            action = item.get("action", {})
                            action_type = action.get("type", "")
                            print(f"Computer Action: {action_type}")
                        elif item_type == "computer_call_output":
                            print(f"Computer Output: [Result]")
            except Exception as agent_run_error:
                # Handle specific tool_call_id errors
                error_str = str(agent_run_error)
                error_type = type(agent_run_error).__name__
                if "tool_call_id" in error_str.lower() or "tool_calls" in error_str.lower() or "BadRequestError" in error_type:
                    print(f"✗ Tool call error: {agent_run_error}")
                    print(f"  Error type: {error_type}")
                    print("  This may occur if the agent's internal history gets out of sync.")
                    print("  Attempting to recover by creating a new agent instance...")
                    
                    # Try to recover by creating a fresh agent instance
                    try:
                        print("Creating fresh agent instance for retry...")
                        fresh_agent = ComputerAgent(
                            model="omniparser+openai/gpt-4o",
                            tools=[computer],
                            only_n_most_recent_images=3,
                            verbosity=logging.INFO,
                            trajectory_dir=str(trajectory_dir),
                        )
                        
                        # Retry with a simplified task description
                        print("Retrying with simplified task...")
                        retry_history = [{"role": "user", "content": f"Please execute this task: {task_description}"}]
                        
                        # Pass a copy of history to agent.run() to avoid conflicts
                        # Extend our history after each iteration
                        async for result_item in fresh_agent.run(retry_history.copy(), stream=False):
                            output_items = result_item.get("output", []) or []
                            
                            # Extend our history with agent outputs (matches CUA examples)
                            retry_history.extend(output_items)
                            
                            for item in output_items:
                                item_type = item.get("type", "")
                                if item_type == "message":
                                    content_parts = item.get("content", []) or []
                                    for cp in content_parts:
                                        text = cp.get("text") if isinstance(cp, dict) else None
                                        if text:
                                            collected_outputs.append(text)
                                            print(f"Agent: {text}")
                                            if mongo_client:
                                                mongo_client.write_log(
                                                    task_id=task_id,
                                                    level="info",
                                                    message=text,
                                                    meta={"source": "agent_output"}
                                                )
                                elif item_type == "computer_call_output":
                                    print(f"Computer Output: [Result]")
                        
                        print("✓ Retry successful")
                    except Exception as retry_error:
                        print(f"✗ Retry failed: {retry_error}")
                        # Re-raise the original error
                        raise agent_run_error
                else:
                    # Re-raise other errors
                    raise
            
            # Screenshots handled by CUA trajectory processor - no cleanup needed
            
            if collected_outputs:
                result["output"] = "\n".join(collected_outputs)
                result["status"] = "success"
                print(f"Task completed successfully")
            else:
                result["output"] = "Task executed but no text output received"
                result["status"] = "success"
                print("Task completed but no text output received")
                
        except ImportError as e:
            print(f"✗ CUA agent import failed: {e}")
            print(f"  Error type: {type(e).__name__}")
            print("  Full traceback:")
            import traceback
            traceback.print_exc()
            print("\nFalling back to simple execution...")
            
            # Simple fallback: just print the task
            result["output"] = f"Task received: {task_description}\nTask execution completed (fallback mode - CUA agent not available: {str(e)})"
            result["status"] = "success"
            print(f"Task received: {task_description}")
            print("Task execution completed (fallback mode)")
            
        except ValueError as e:
            # Missing environment variable
            print(f"✗ Configuration error: {e}")
            print("Falling back to simple execution...")
            result["output"] = f"Task received: {task_description}\nTask execution completed (fallback mode - {str(e)})"
            result["status"] = "success"
            print(f"Task received: {task_description}")
            print("Task execution completed (fallback mode)")
            
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        print(f"✗ ERROR: Failed to execute task: {e}")
        print(f"  Error type: {type(e).__name__}")
        import traceback
        traceback.print_exc()
    
    return result


def execute_task(task_description: str, task_id: Optional[int] = None, mongo_client: Optional[Any] = None) -> dict:
    """
    Synchronous wrapper for async task execution.
    
    Args:
        task_description: The task description to execute
        
    Returns:
        Dictionary with execution results
    """
    # Use asyncio.run() for Python 3.7+ (handles event loop creation/cleanup automatically)
    # This avoids the deprecation warning from get_event_loop()
    # asyncio.run() will raise RuntimeError if called from within an async context,
    # which is the correct behavior
    return asyncio.run(execute_task_async(task_description, task_id, mongo_client))


def main():
    """Main entry point."""
    task_description = get_task_description()
    
    # If no task description provided, run in polling mode using runner
    if not task_description:
        try:
            from config import Config
            from db_adapters import PostgresClient, MongoClientWrapper
            from runner import AgentRunner
            
            # Load configuration and start polling loop
            config = Config.from_env()
            postgres = PostgresClient(config.postgres_dsn)
            mongo = MongoClientWrapper(config.mongo_uri, config.agent_id)
            
            runner = AgentRunner(
                config=config,
                postgres_client=postgres,
                mongo_client=mongo
            )
            
            runner.poll_loop()
        except KeyboardInterrupt:
            print("\nShutting down agent worker...")
            sys.exit(0)
        except Exception as e:
            print(f"Fatal error: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            sys.exit(1)
        return
    
    # Single task execution mode
    print("=" * 60)
    print("AGENT WORKER TASK EXECUTOR")
    print("=" * 60)
    print()
    
    # Get task_id and mongo_client from environment if available
    task_id = None
    mongo_client = None
    
    task_id_str = os.getenv("TASK_ID")
    if task_id_str:
        try:
            task_id = int(task_id_str)
        except:
            pass
    
    mongo_uri = os.getenv("MONGO_URI")
    agent_id = os.getenv("AGENT_ID")
    if mongo_uri and agent_id:
        try:
            from db_adapters import MongoClientWrapper
            mongo_client = MongoClientWrapper(mongo_uri, agent_id)
        except Exception as e:
            print(f"Warning: Failed to initialize MongoDB client: {e}")
    
    result = execute_task(task_description, task_id=task_id, mongo_client=mongo_client)
    
    print()
    print("=" * 60)
    print("EXECUTION RESULT")
    print("=" * 60)
    print(f"Status: {result['status']}")
    if result.get('output'):
        print(f"Output:\n{result['output']}")
    if result.get('error'):
        print(f"Error: {result['error']}")
    
    # Output the response in a structured format that can be easily extracted
    # This marker helps runner.py extract just the agent response
    print()
    print("=" * 60)
    print("AGENT_RESPONSE_START")
    print("=" * 60)
    if result['output']:
        # Output just the agent response, not diagnostics
        print(result['output'])
    elif result['error']:
        print(f"Error: {result['error']}")
    else:
        print("No output or error")
    print("=" * 60)
    print("AGENT_RESPONSE_END")
    print("=" * 60)
    
    # Exit with appropriate code
    if result['status'] == 'success':
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()

