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
    scorer = ScoringEngine(logger=logger)
    llm = LLMInterface(logger=logger)
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
                    
                    # Get the latest score for each agent
                    if report.get("scores") and isinstance(report["scores"], dict):
                        final_score = report["scores"].get("final_score", 0)
                        # Convert to percentage if it's a fraction (0-1)
                        if final_score <= 1.0:
                            final_score *= 100
                        
                        # Update agent score (will keep updating to latest)
                        agent_scores[agent_id] = {
                            "score": round(final_score, 2),
                            "task_id": report.get("task_id"),
                            "evaluated_at": report.get("evaluated_at")
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
            
            return {
                "status": "running",
                "scheduler_active": scheduler.running,
                "total_evaluations": total_evaluations,
                "agents_evaluated": len(agents),
                "tasks_evaluated": len(tasks),
                "average_score": round(avg_score, 2),
                "agent_scores": agent_scores,
                "recent_evaluations": all_reports[:5] if all_reports else []
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
