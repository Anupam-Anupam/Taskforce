#!/usr/bin/env python3
"""
Test script to verify the /evaluator/status endpoint returns properly normalized data.
This helps verify that:
1. agent_scores contains proper breakdown with correctness, efficiency, etc.
2. agent_feedback includes performance_details with metrics
3. Agent IDs are properly aligned between backend and frontend
"""

import asyncio
import json
import httpx
import sys
from pathlib import Path

# Add the workspace to the path
workspace_root = Path(__file__).parent
sys.path.insert(0, str(workspace_root))

async def test_evaluator_status(base_url: str = "http://localhost:8001"):
    """Test the /evaluator/status endpoint."""
    
    print("=" * 80)
    print("Testing /evaluator/status endpoint")
    print("=" * 80)
    print(f"Base URL: {base_url}\n")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Hit the evaluator/status endpoint via server proxy
            print("Fetching /evaluator/status...")
            response = await client.get(f"{base_url}/evaluator/status")
            response.raise_for_status()
            
            data = response.json()
            
            print("\n✓ Successfully fetched /evaluator/status\n")
            
            # Check top-level structure
            print("Top-level keys:")
            for key in sorted(data.keys()):
                print(f"  - {key}")
            
            # Check agent_scores
            print("\n" + "=" * 80)
            print("AGENT_SCORES Analysis")
            print("=" * 80)
            agent_scores = data.get("agent_scores", {})
            print(f"Number of agents in agent_scores: {len(agent_scores)}")
            
            if agent_scores:
                for agent_id, score_data in agent_scores.items():
                    print(f"\nAgent: {agent_id}")
                    print(f"  Score: {score_data.get('score')}%")
                    print(f"  Task ID: {score_data.get('task_id')}")
                    print(f"  Is Completed: {score_data.get('is_completed')}")
                    
                    # Check breakdown
                    breakdown = score_data.get("breakdown", {})
                    print(f"  Breakdown keys: {list(breakdown.keys())}")
                    if breakdown:
                        for key, val in breakdown.items():
                            print(f"    - {key}: {val}")
                    else:
                        print("    ⚠ WARNING: No breakdown data!")
                    
                    # Check metrics
                    metrics = score_data.get("metrics", {})
                    print(f"  Metrics keys: {list(metrics.keys())}")
                    if metrics:
                        for key in ["completion_time_s", "error_count", "total_api_calls", "cost_usd"]:
                            val = metrics.get(key)
                            if val is not None:
                                print(f"    - {key}: {val}")
                    else:
                        print("    ⚠ WARNING: No metrics data!")
                    
                    # Check penalties
                    penalties = score_data.get("penalties", {})
                    if penalties and any(v > 0 for v in penalties.values()):
                        print(f"  Penalties: {penalties}")
            else:
                print("⚠ WARNING: No agents in agent_scores!")
            
            # Check agent_feedback
            print("\n" + "=" * 80)
            print("AGENT_FEEDBACK Analysis")
            print("=" * 80)
            agent_feedback = data.get("agent_feedback", {})
            print(f"Number of agents in agent_feedback: {len(agent_feedback)}")
            
            if agent_feedback:
                for agent_id, feedback in agent_feedback.items():
                    print(f"\nAgent: {agent_id}")
                    print(f"  Feedback keys: {list(feedback.keys())}")
                    
                    # Check performance_details
                    perf_details = feedback.get("performance_details", {})
                    if perf_details:
                        print(f"  ✓ Has performance_details")
                        print(f"    - Score: {perf_details.get('score')}%")
                        print(f"    - Breakdown keys: {list(perf_details.get('breakdown', {}).keys())}")
                        print(f"    - Metrics keys: {list(perf_details.get('metrics', {}).keys())}")
                    else:
                        print(f"  ⚠ WARNING: No performance_details in feedback!")
                    
                    # Check other feedback fields
                    if feedback.get("score"):
                        print(f"  Score: {feedback.get('score')}")
                    if feedback.get("strengths"):
                        print(f"  Strengths: {feedback.get('strengths')[:1]}...")
                    if feedback.get("weaknesses"):
                        print(f"  Weaknesses: {feedback.get('weaknesses')[:1]}...")
            else:
                print("⚠ WARNING: No agents in agent_feedback!")
            
            # Check recent_evaluations
            print("\n" + "=" * 80)
            print("RECENT_EVALUATIONS Analysis")
            print("=" * 80)
            recent_evals = data.get("recent_evaluations", [])
            print(f"Number of recent evaluations: {len(recent_evals)}")
            
            if recent_evals:
                for i, eval_item in enumerate(recent_evals[:2]):  # Show first 2
                    print(f"\nEvaluation {i+1}:")
                    print(f"  Task ID: {eval_item.get('task_id')}")
                    print(f"  Agent ID: {eval_item.get('agent_id')}")
                    print(f"  Score: {eval_item.get('scores', {}).get('final_score')}")
                    print(f"  Has metrics: {bool(eval_item.get('metrics'))}")
                    print(f"  Has breakdown: {bool(eval_item.get('breakdown'))}")
            
            # Summary
            print("\n" + "=" * 80)
            print("SUMMARY")
            print("=" * 80)
            
            issues = []
            
            # Check if agent_scores have proper structure
            for agent_id, score_data in agent_scores.items():
                breakdown = score_data.get("breakdown", {})
                if not breakdown:
                    issues.append(f"Agent {agent_id}: No breakdown in agent_scores")
                
                metrics = score_data.get("metrics", {})
                if not metrics:
                    issues.append(f"Agent {agent_id}: No metrics in agent_scores")
            
            # Check if agent_feedback has performance_details
            for agent_id, feedback in agent_feedback.items():
                perf_details = feedback.get("performance_details")
                if not perf_details:
                    issues.append(f"Agent {agent_id}: No performance_details in agent_feedback")
            
            if issues:
                print("⚠ Issues found:")
                for issue in issues:
                    print(f"  - {issue}")
            else:
                print("✓ All checks passed! Backend data is properly normalized.")
            
            # Print full JSON for debugging
            print("\n" + "=" * 80)
            print("Full Response JSON (first 3000 chars):")
            print("=" * 80)
            print(json.dumps(data, indent=2)[:3000])
            
    except httpx.ConnectError:
        print(f"✗ Connection error: Could not connect to {base_url}")
        print("  Make sure the server is running on port 8001")
        return False
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == "__main__":
    # Try local server first
    result = asyncio.run(test_evaluator_status("http://localhost:8001"))
    sys.exit(0 if result else 1)
