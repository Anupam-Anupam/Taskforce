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
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
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


class Health(BaseModel):
    status: str


def build_score_breakdown(report_scores: dict, metrics: dict, is_completed: bool = False) -> dict:
    """
    Build a score breakdown dictionary from available scores and metrics.
    Maps the simplified scoring structure to the detailed breakdown expected by the frontend.
    """
    # Get output_score (0-100) and final_score (0-1)
    output_score = report_scores.get("output_score", 0.0)
    final_score = report_scores.get("final_score", 0.0)
    
    # Normalize output_score to 0-1 range if needed
    if output_score > 1.0:
        output_score_normalized = output_score / 100.0
    else:
        output_score_normalized = output_score
    
    # Normalize final_score to 0-1 range if needed
    if final_score > 1.0:
        final_score_normalized = final_score / 100.0
    else:
        final_score_normalized = final_score
    
    # If task is completed, set correctness to 1.0 (100%)
    if is_completed:
        correctness = 1.0
    else:
        # Use output_score as correctness (normalized to 0-1)
        correctness = output_score_normalized
    
    # Calculate other metrics based on available data
    completion_time = float(metrics.get("completion_time_s", 0.0) or 0.0)
    error_count = float(metrics.get("error_count", 0) or 0)
    retry_count = float(metrics.get("retry_count", 0) or 0)
    total_api_calls = float(metrics.get("total_api_calls", 0) or 0)
    cost_usd = float(metrics.get("cost_usd", 0.0) or 0.0)
    
    # Efficiency: based on completion time and API calls
    # Lower time and fewer API calls = higher efficiency
    # Normalize: 0-300s = 1.0, 300-600s = 0.5-1.0, 600s+ = 0.0-0.5
    # If completion_time is 0 or missing, we can't calculate efficiency - use a default based on other metrics
    if completion_time <= 0:
        # If we have API calls but no time, assume moderate efficiency
        if total_api_calls > 0:
            efficiency = 0.7  # Moderate efficiency if we have activity but no time data
        else:
            efficiency = 0.5  # Unknown - use neutral value
    elif completion_time <= 300:
        efficiency = 1.0
    elif completion_time <= 600:
        efficiency = 1.0 - ((completion_time - 300) / 600.0) * 0.5
    else:
        efficiency = max(0.0, 0.5 - ((completion_time - 600) / 600.0) * 0.5)
    
    # Penalize for excessive API calls
    if total_api_calls > 50:
        api_penalty = min(0.3, (total_api_calls - 50) / 200.0)
        efficiency = max(0.0, efficiency - api_penalty)
    
    # Quality: based on correctness and error rate
    # Higher correctness and fewer errors = higher quality
    error_penalty = min(0.5, error_count * 0.1)
    quality = max(0.0, correctness - error_penalty)
    
    # Stability: based on error count and retry count
    # Fewer errors and retries = higher stability
    stability = max(0.0, 1.0 - (error_count * 0.15) - (retry_count * 0.1))
    stability = min(1.0, stability)
    
    # Autonomy: based on human/agent requests (dependencies)
    # Fewer dependencies = higher autonomy
    deps = float(metrics.get("human_or_agent_requests", 0) or 0)
    autonomy = max(0.0, 1.0 - (deps * 0.2))
    autonomy = min(1.0, autonomy)
    
    # Resource efficiency: based on cost and memory usage
    # Lower cost = higher resource efficiency
    # Normalize: $0-0.10 = 1.0, $0.10-1.00 = 0.5-1.0, $1.00+ = 0.0-0.5
    # If cost is 0, check if we have API calls - if yes, cost data might be missing
    if cost_usd <= 0:
        # If we have API calls but no cost, assume moderate efficiency
        if total_api_calls > 0:
            resource_efficiency = 0.7  # Moderate efficiency if we have activity but no cost data
        else:
            resource_efficiency = 0.5  # Unknown - use neutral value
    elif cost_usd <= 0.10:
        resource_efficiency = 1.0
    elif cost_usd <= 1.00:
        resource_efficiency = 1.0 - ((cost_usd - 0.10) / 0.90) * 0.5
    else:
        resource_efficiency = max(0.0, 0.5 - ((cost_usd - 1.00) / 2.00) * 0.5)
    
    # Also consider memory usage if available
    memory_mb = float(metrics.get("memory_usage_mb", 0.0) or 0.0)
    if memory_mb > 1000:  # > 1GB
        resource_efficiency = max(0.0, resource_efficiency - 0.2)
    
    return {
        "correctness": round(correctness, 4),
        "efficiency": round(efficiency, 4),
        "quality": round(quality, 4),
        "stability": round(stability, 4),
        "autonomy": round(autonomy, 4),
        "resource_efficiency": round(resource_efficiency, 4),
    }


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
            
            # Get unique agents and tasks
            agents = set()
            tasks = set()
            total_score = 0
            score_count = 0
            
            # Track latest score per agent for the current task
            agent_scores = {}
            
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
                        
                        # Build detailed breakdown from scores and metrics
                        report_scores = report.get("scores", {})
                        report_metrics = report.get("metrics", {})
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
            
            # Generate structured feedback for each agent
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
            
            return {
                "status": "running",
                "scheduler_active": scheduler.running,
                "total_evaluations": total_evaluations,
                "agents_evaluated": len(agents),
                "tasks_evaluated": len(tasks),
                "average_score": round(avg_score, 2),
                "agent_scores": agent_scores,
                "agent_feedback": agent_feedback,
                "recent_evaluations": recent_evaluations[:5]  # Limit to top 5
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
