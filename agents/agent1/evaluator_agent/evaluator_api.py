import json
import logging
import os
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import sys
from pathlib import Path
# Add parent directories to path to find storage module
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from storage import MongoAdapter, PostgresAdapter
from modules.data_collector import DataCollector
from modules.scoring_engine import ScoringEngine
from modules.llm_interface import LLMInterface
from modules.scheduler import EvaluatorScheduler
from modules.report_builder import ReportBuilder
from modules.visualization import build_performance_figure, figure_to_png_bytes
from fastapi.responses import Response


# Simple structured logging
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("evaluator_agent")


def build_score_breakdown(scores: dict, metrics: dict, is_completed: bool) -> dict:
    """
    Build a breakdown of 6 evaluation metrics from scores and raw metrics.
    
    Metrics:
    - correctness: How correct the output is (from output_score if available)
    - efficiency: How efficiently the task was completed (based on API calls and cost)
    - quality: Overall quality of the output (from quality_score if available)
    - stability: How stable the agent's behavior is (from stability score if available)
    - autonomy: How autonomously the agent worked (binary: 0 or 1)
    - resource_efficiency: How efficiently resources were used (inverse of cost/time)
    """
    if not scores:
        scores = {}
    if not metrics:
        metrics = {}
    
    # Extract base scores
    output_score = float(scores.get("output_score", 0)) or 0
    quality_score = float(scores.get("quality_score", 0)) or 0
    stability_score = float(scores.get("stability_score", 0)) or 0
    autonomy_score = float(scores.get("autonomy_score", 0)) or 0
    
    # Normalize to 0-1 range (in case they're already percentages)
    if output_score > 1:
        output_score = output_score / 100
    if quality_score > 1:
        quality_score = quality_score / 100
    if stability_score > 1:
        stability_score = stability_score / 100
    if autonomy_score > 1:
        autonomy_score = autonomy_score / 100
    
    # Calculate efficiency (inverse of normalized cost - lower cost = higher efficiency)
    # If no cost data, assume full efficiency
    cost = float(metrics.get("cost_usd", 0)) or 0
    api_calls = int(metrics.get("total_api_calls", 0)) or 0
    
    # Efficiency: 1.0 if cost < $0.01, decay exponentially after that
    # Each $0.10 costs 10% efficiency
    efficiency_score = max(0, 1.0 - (cost * 10))
    
    # Resource efficiency: inverse of cost per API call
    # 1.0 if no API calls or cost, decay based on cost/call ratio
    if api_calls > 0 and cost > 0:
        cost_per_call = cost / api_calls
        resource_efficiency = max(0, 1.0 - (cost_per_call * 100))  # Decay quickly for expensive calls
    else:
        resource_efficiency = 1.0
    
    # Build the breakdown dict with all 6 metrics (0-1 range)
    breakdown = {
        "correctness": output_score,
        "efficiency": efficiency_score,
        "quality": quality_score,
        "stability": stability_score,
        "autonomy": autonomy_score,
        "resource_efficiency": resource_efficiency,
    }
    
    return breakdown


class Health(BaseModel):
    status: str


def create_app() -> FastAPI:
    app = FastAPI(title="Evaluator Agent API", version="1.0.0")

    # Add CORS middleware to allow frontend access
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    mongo = MongoAdapter(cluster_mode=True)
    pg = PostgresAdapter()

    collector = DataCollector(mongo=mongo, pg=pg, logger=logger)
    llm = LLMInterface(logger=logger)
    scorer = ScoringEngine(logger=logger, llm=llm)
    builder = ReportBuilder(logger=logger)
    scheduler = EvaluatorScheduler(collector, scorer, llm, builder, logger=logger)

    # Kick off periodic evaluations
    scheduler.start()

    @app.get("/health", response_model=Health)
    def health() -> Health:
        return Health(status="ok")
    
    @app.get("/status")
    def get_status():
        """Get evaluator status and summary statistics."""
        try:
            all_reports = scheduler.get_all_reports()
            
            # Calculate summary statistics
            total_evaluations = len(all_reports)
            
            # Get unique agents from database (for persistent scoring)
            db_agents = pg.get_unique_agents()
            
            # Get unique agents and tasks
            agents = set(db_agents) if db_agents else set()
            tasks = set()
            total_score = 0
            score_count = 0
            
            # Track latest score per agent - PRIMARY: use scheduler reports for real-time updates
            agent_scores = {}
            
            # First pass: Populate from scheduler reports (active evaluations with real-time data)
            for report in all_reports:
                agent_id = report.get("agent_id")
                if agent_id:
                    agents.add(agent_id)
                    
                    # Check if task is completed
                    task_id = report.get("task_id")
                    is_completed = False
                    if task_id:
                        try:
                            task_id_int = int(task_id)
                            task = pg.get_task(task_id_int)
                            if task and str(task.get("status", "")).lower() == "completed":
                                is_completed = True
                        except Exception:
                            pass
                    
                    # Get the latest score for each agent
                    if report.get("scores") and isinstance(report["scores"], dict):
                        # If task is completed, set score to 100%
                        if is_completed:
                            final_score = 100.0
                        else:
                            final_score = report["scores"].get("final_score", 0)
                        # Convert to percentage if it's a fraction (0-1)
                        if final_score <= 1.0:
                            final_score *= 100
                        
                        # Build detailed breakdown with correctness, efficiency, etc.
                        report_scores = report.get("scores", {})
                        report_metrics = report.get("metrics", {})
                        
                        # If metrics are missing/empty, extract them from MongoDB logs
                        if not report_metrics or len(report_metrics) == 0:
                            report_metrics = collector.extract_raw_metrics_for_task(agent_id, task_id) if task_id else {}
                        
                        breakdown = build_score_breakdown(report_scores, report_metrics, is_completed)
                        
                        # Update agent score (will keep updating to latest)
                        agent_scores[agent_id] = {
                            "score": round(final_score, 2),
                            "task_id": task_id,
                            "evaluated_at": report.get("evaluated_at"),
                            "breakdown": breakdown,
                            "metrics": report_metrics,
                            "penalties": report.get("penalties", {}),
                            "summary": report.get("evaluation_summary", ""),
                            "is_completed": is_completed
                        }
                
                if report.get("task_id"):
                    tasks.add(report["task_id"])
                    
                if report.get("scores") and isinstance(report["scores"], dict):
                    # Try overall_score first, then final_score
                    overall_score = report["scores"].get("overall_score") or report["scores"].get("final_score", 0)
                    if overall_score > 0:
                        # Convert to percentage if it's a fraction (0-1)
                        if overall_score <= 1.0:
                            overall_score *= 100
                        total_score += overall_score
                        score_count += 1
            
            avg_score = (total_score / score_count) if score_count > 0 else 0
            
            # SECOND PASS: For agents in database without scheduler reports (no active runs),
            # fetch their most recent evaluation from database to ensure persistent scoring
            agents_in_db = set(db_agents) if db_agents else set()
            agents_with_scores = set(agent_scores.keys())
            agents_needing_persistent_score = agents_in_db - agents_with_scores
            
            for agent_id in agents_needing_persistent_score:
                try:
                    # Get most recent task for this agent
                    recent_tasks = pg.get_tasks(agent_id=agent_id, limit=1)
                    
                    if recent_tasks:
                        task = recent_tasks[0]
                        task_id = str(task.get("id", ""))
                        is_completed = str(task.get("status", "")).lower() == "completed"
                        
                        # FAST: Extract raw metrics from MongoDB logs (no evaluation computation)
                        raw_metrics = collector.extract_raw_metrics_for_task(agent_id, task_id)
                        
                        # If we found metrics, show them with basic score
                        if raw_metrics:
                            # For agents with no active evaluation, use a simple score based on task completion
                            score = 100.0 if is_completed else 0.0
                            
                            agent_scores[agent_id] = {
                                "score": round(score, 2),
                                "task_id": task_id,
                                "evaluated_at": task.get("updated_at", ""),
                                "breakdown": {},  # No breakdown for persistent (non-evaluated) scores
                                "metrics": raw_metrics,
                                "penalties": {},
                                "summary": "Score unavailable (no active evaluation)" if not is_completed else "Task completed",
                                "is_completed": is_completed
                            }
                        
                except Exception as e:
                    logger.warning(json.dumps({
                        "event": "persistent_scoring_from_db_error",
                        "agent_id": agent_id,
                        "error": str(e)
                    }))
            
            agent_feedback = {}
            for agent_id in agents:
                agent_reports = scheduler.get_agent_reports(agent_id)
                if agent_reports:
                    # Collect actual task data (logs, requests, outputs) for LLM analysis
                    task_data_list = []
                    for report in agent_reports[:5]:  # Get data for up to 5 most recent tasks
                        task_id = report.get("task_id")
                        if task_id:
                            try:
                                task_data = collector.collect_for_task(agent_id, task_id)
                                task_data_list.append(task_data)
                            except Exception as e:
                                logger.warning(json.dumps({
                                    "event": "collect_task_data_for_feedback_error",
                                    "agent_id": agent_id,
                                    "task_id": task_id,
                                    "error": str(e)
                                }))
                    
                    feedback = llm.generate_structured_feedback(agent_id, agent_reports, task_data_list)
                    
                    # Attach latest performance card data so frontend can reuse this payload
                    agent_performance = agent_scores.get(agent_id)
                    if agent_performance:
                        feedback["performance_details"] = {
                            "score": agent_performance.get("score", 0),
                            "is_completed": agent_performance.get("is_completed", False),
                            "task_id": agent_performance.get("task_id"),
                            "evaluated_at": agent_performance.get("evaluated_at"),
                            "breakdown": agent_performance.get("breakdown", {}),
                            "metrics": agent_performance.get("metrics", {}),
                            "penalties": agent_performance.get("penalties", {}),
                            "summary": agent_performance.get("summary", ""),
                        }
                    
                    agent_feedback[agent_id] = feedback
            
            # Calculate recent evaluations with real scores from MongoDB logs
            recent_evaluations = []
            try:
                # Get recent tasks from PostgreSQL (most recent first)
                recent_tasks = pg.get_tasks(limit=20)
                if recent_tasks:
                    # Sort by task ID descending to get most recent
                    recent_tasks.sort(key=lambda t: int(t.get("id", 0) or 0), reverse=True)
                    
                    # Process up to 5 most recent tasks
                    processed_count = 0
                    for task in recent_tasks[:5]:
                        if processed_count >= 5:
                            break
                        
                        task_id = str(task.get("id", ""))
                        agent_id = task.get("agent_id")
                        
                        if not task_id or not agent_id:
                            continue
                        
                        try:
                            # Collect task data from MongoDB logs
                            task_data = collector.collect_for_task(agent_id, task_id)
                            
                            # Calculate score using the same scoring engine as agent feedback
                            score_pack = scorer.score_task(task_data)
                            
                            # Generate summary
                            summary = llm.summarize({**task_data, **score_pack})
                            
                            # Build evaluation report
                            evaluation = builder.build_report(task_data, score_pack, summary)
                            
                            # Add initial_request for frontend display
                            evaluation["initial_request"] = task_data.get("initial_request", "")
                            
                            # Check if task is completed
                            is_completed = False
                            try:
                                task_id_int = int(task_id)
                                task_info = pg.get_task(task_id_int)
                                if task_info and str(task_info.get("status", "")).lower() == "completed":
                                    is_completed = True
                                    # Override final score to 100% if completed
                                    if evaluation.get("scores"):
                                        evaluation["scores"]["final_score"] = 1.0
                                        evaluation["scores"]["output_score"] = 100.0
                            except Exception:
                                pass
                            
                            recent_evaluations.append(evaluation)
                            processed_count += 1
                            
                        except Exception as e:
                            logger.warning(json.dumps({
                                "event": "recent_evaluation_error",
                                "task_id": task_id,
                                "agent_id": agent_id,
                                "error": str(e)
                            }))
                            continue
                    
                    # Sort by task_id descending (most recent first)
                    recent_evaluations.sort(key=lambda e: int(e.get("task_id", 0) or 0), reverse=True)
            except Exception as e:
                logger.error(json.dumps({
                    "event": "recent_evaluations_error",
                    "error": str(e)
                }))
                # Fallback to cached reports if calculation fails
                recent_evaluations = all_reports[:5] if all_reports else []
            
            performance_instructions = (
                "Agents must fetch and report their number of errors, total cost, completion time, and API calls before these scores refresh."
            )
            
            return {
                "status": "running",
                "scheduler_active": scheduler.running,
                "total_evaluations": total_evaluations,
                "agents_evaluated": len(agents),
                "tasks_evaluated": len(tasks),
                "average_score": round(avg_score, 2),
                "agent_scores": agent_scores,
                "agent_feedback": agent_feedback,
                "recent_evaluations": recent_evaluations[:5],  # Limit to top 5
                "performance_instructions": performance_instructions
            }
        except Exception as e:
            logger.error(json.dumps({
                "event": "status_error",
                "error": str(e)
            }))
            return {
                "status": "error",
                "error": str(e),
                "scheduler_active": False,
                "total_evaluations": 0,
                "agent_scores": {}
            }

    @app.get("/task/{task_id}")
    def get_task(task_id: str):
        report = scheduler.get_task_report(task_id)
        if not report:
            # Try on-demand evaluation for this task (best-effort)
            try:
                data = collector.collect_for_task(agent_id=os.getenv("DEFAULT_AGENT_ID"), task_id=task_id)
                pack = scorer.score_task(data)
                summary = llm.summarize({**data, **pack})
                report = builder.build_report(data, pack, summary)
                return report
            except Exception:
                pass
            raise HTTPException(status_code=404, detail="Report not found")
        # Force re-evaluation with new scoring formula
        try:
            data = collector.collect_for_task(agent_id=report.get("agent_id"), task_id=task_id)
            pack = scorer.score_task(data)
            summary = llm.summarize({**data, **pack})
            report = builder.build_report(data, pack, summary)
        except Exception:
            pass  # Return cached report if re-evaluation fails
        return report

    @app.get("/agent/{agent_id}")
    def get_agent(agent_id: str):
        reports = scheduler.get_agent_reports(agent_id)
        if not reports:
            raise HTTPException(status_code=404, detail="No reports for agent")
        return reports

    @app.get("/reports")
    def get_reports():
        return scheduler.get_all_reports()

    @app.get("/agent/{agent_id}/performance.png")
    def agent_performance_png(agent_id: str):
        try:
            reports = scheduler.get_agent_reports(agent_id)
            if not reports:
                raise HTTPException(status_code=404, detail="No reports for agent")
            fig = build_performance_figure(reports)
            png = figure_to_png_bytes(fig)
            return Response(content=png, media_type="image/png")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(json.dumps({"event": "plot_render_error", "scope": "agent", "agent_id": agent_id, "error": str(e)}))
            return Response(content=f"plot render error: {e}", media_type="text/plain", status_code=503)

    @app.get("/task/{task_id}/performance.png")
    def task_performance_png(task_id: str):
        try:
            # Build per-progress snapshots to ensure a point for each update
            snapshots = collector.collect_snapshots_for_task(agent_id=os.getenv("DEFAULT_AGENT_ID"), task_id=task_id)
            reports = []
            for snap in snapshots:
                pack = scorer.score_task(snap)
                summary = llm.summarize({**snap, **pack})
                rep = builder.build_report(snap, pack, summary)
                # carry forward snapshot collected_at as evaluated_at for plotting continuity
                if "collected_at" in snap:
                    rep["evaluated_at"] = snap["collected_at"]
                reports.append(rep)
            fig = build_performance_figure(reports)
            png = figure_to_png_bytes(fig)
            return Response(content=png, media_type="image/png")
        except Exception as e:
            logger.error(json.dumps({"event": "plot_render_error", "scope": "task", "task_id": task_id, "error": str(e)}))
            return Response(content=f"plot render error: {e}", media_type="text/plain", status_code=503)

    @app.get("/agents/progress/graph")
    def generate_agents_progress_graph():
        """
        Generate a progress graph for all agents based on their most recent task.
        Accesses MongoDB logs for each agent, analyzes progress at each step,
        and returns a screenshot saved to the local machine.
        """
        try:
            agent_ids = ["agent1", "agent2", "agent3"]
            agent_snapshots = {}
            
            # Get most recent task for each agent and collect progress snapshots
            for agent_id in agent_ids:
                try:
                    logger.info(json.dumps({
                        "event": "starting_agent_check",
                        "agent_id": agent_id
                    }))
                    
                    # Get most recent task ID for this agent
                    task_id = collector.get_most_recent_task_for_agent(agent_id)
                    
                    logger.info(json.dumps({
                        "event": "checking_agent_task",
                        "agent_id": agent_id,
                        "task_id": task_id
                    }))
                    
                    if not task_id:
                        logger.warning(json.dumps({
                            "event": "no_recent_task",
                            "agent_id": agent_id
                        }))
                        continue
                    
                    logger.info(json.dumps({
                        "event": "collecting_snapshots",
                        "agent_id": agent_id,
                        "task_id": task_id
                    }))
                    
                    # Collect progress snapshots for this agent's task
                    snapshots = collector.collect_progress_snapshots_for_agent_task(agent_id, task_id)
                    
                    logger.info(json.dumps({
                        "event": "snapshots_collected",
                        "agent_id": agent_id,
                        "task_id": task_id,
                        "snapshot_count": len(snapshots) if snapshots else 0
                    }))
                    
                    if snapshots:
                        agent_snapshots[agent_id] = snapshots
                        logger.info(json.dumps({
                            "event": "collected_agent_snapshots",
                            "agent_id": agent_id,
                            "task_id": task_id,
                            "snapshot_count": len(snapshots)
                        }))
                    else:
                        logger.warning(json.dumps({
                            "event": "no_snapshots_collected",
                            "agent_id": agent_id,
                            "task_id": task_id
                        }))
                except Exception as e:
                    import traceback
                    logger.error(json.dumps({
                        "event": "collect_agent_error",
                        "agent_id": agent_id,
                        "error": str(e),
                        "traceback": traceback.format_exc()
                    }))
                    continue
            
            if not agent_snapshots:
                raise HTTPException(
                    status_code=404,
                    detail="No progress data found for any agent"
                )
            
            # Build multi-agent progress figure
            from modules.visualization import build_multi_agent_progress_figure, figure_to_png_bytes
            
            fig = build_multi_agent_progress_figure(agent_snapshots)
            
            # Convert figure to PNG bytes and then to base64
            import base64
            png_bytes = figure_to_png_bytes(fig)
            image_base64 = base64.b64encode(png_bytes).decode('utf-8')
            image_data_url = f"data:image/png;base64,{image_base64}"
            
            # Store metadata in PostgreSQL for history
            try:
                timestamp = datetime.now()
                # Store as evaluation or create a progress_graphs table entry
                # For now, we'll just return it - can add storage later if needed
                logger.info(json.dumps({
                    "event": "progress_graph_generated",
                    "agents": list(agent_snapshots.keys()),
                    "snapshot_counts": {agent: len(snapshots) for agent, snapshots in agent_snapshots.items()},
                    "timestamp": timestamp.isoformat()
                }))
            except Exception as e:
                logger.warning(json.dumps({
                    "event": "progress_graph_metadata_save_failed",
                    "error": str(e)
                }))
            
            # Return response with image data URL
            return {
                "status": "success",
                "image_data_url": image_data_url,
                "agents": list(agent_snapshots.keys()),
                "snapshot_counts": {agent: len(snapshots) for agent, snapshots in agent_snapshots.items()},
                "timestamp": datetime.now().isoformat(),
                "message": "Progress graph generated successfully"
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(json.dumps({
                "event": "progress_graph_error",
                "error": str(e)
            }))
            raise HTTPException(
                status_code=500,
                detail=f"Failed to generate progress graph: {str(e)}"
            )

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8001")))
