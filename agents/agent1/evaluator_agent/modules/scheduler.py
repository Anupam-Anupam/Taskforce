import os
import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional

from .data_collector import DataCollector
from .scoring_engine import ScoringEngine
from .llm_interface import LLMInterface
from .report_builder import ReportBuilder
from .persistence import HistoryStore


class EvaluatorScheduler:
    """Simple interval scheduler to evaluate tasks and store latest reports in memory."""

    def __init__(
        self,
        collector: DataCollector,
        scorer: ScoringEngine,
        llm: LLMInterface,
        builder: ReportBuilder,
        logger: Optional[logging.Logger] = None,
        interval_seconds: Optional[int] = None,
    ) -> None:
        self.collector = collector
        self.scorer = scorer
        self.llm = llm
        self.builder = builder
        self.logger = logger or logging.getLogger(__name__)
        self.interval = int(interval_seconds or os.getenv("SCHEDULE_INTERVAL_SECONDS", "60"))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._reports_by_task: Dict[str, Dict[str, Any]] = {}
        self._reports_by_agent: Dict[str, List[Dict[str, Any]]] = {}
        self._history_by_task: Dict[str, List[Dict[str, Any]]] = {}
        self.history_dir = os.getenv("EVAL_HISTORY_DIR", "/data/history")
        self.store = HistoryStore(self.history_dir, self.logger)
        # Load persisted history
        try:
            loaded = self.store.load_all()
            for rep in loaded:
                task_id = rep.get("task_id")
                agent_id = rep.get("agent_id")
                if not task_id or not agent_id:
                    continue
                self._history_by_task.setdefault(task_id, []).append(rep)
                self._reports_by_agent.setdefault(agent_id, []).append(rep)
                # Track latest per task
                self._reports_by_task[task_id] = rep
            self.logger.info(json.dumps({"event": "history_loaded", "count": len(loaded)}))
        except Exception as e:
            self.logger.error(json.dumps({"event": "history_load_error", "error": str(e)}))

    @property
    def running(self) -> bool:
        """Check if scheduler is currently running."""
        return self._thread is not None and self._thread.is_alive()
    
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, name="evaluator-scheduler", daemon=True)
        self._thread.start()
        self.logger.info(json.dumps({"event": "scheduler_started", "interval": self.interval}))

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self.logger.info(json.dumps({"event": "scheduler_stopped"}))

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.evaluate_all()
            except Exception as e:
                self.logger.error(json.dumps({"event": "evaluate_all_error", "error": str(e)}))
            self._stop.wait(self.interval)

    def evaluate_all(self) -> None:
        data_list = self.collector.collect_all()
        agents = set()
        for d in data_list:
            if d.get("agent_id"):
                agents.add(d["agent_id"])
        num_agents = max(1, len(agents))

        total_reports = 0
        for d in data_list:
            agent_id = d.get("agent_id")
            task_id = d.get("task_id")
            # Build snapshots per progress update so we record intermittent points
            try:
                snapshots = self.collector.collect_snapshots_for_task(agent_id, task_id)
            except Exception as e:
                self.logger.error(json.dumps({"event": "collect_snapshots_error", "task_id": task_id, "error": str(e)}))
                snapshots = [d]

            for snap in snapshots:
                score_pack = self.scorer.score_task(snap, num_agents=num_agents)
                summary = self.llm.summarize({**snap, **score_pack})
                report = self.builder.build_report(snap, score_pack, summary)
                # prefer snapshot collected_at for timeline if present
                if "collected_at" in snap:
                    report["evaluated_at"] = snap["collected_at"]

                task_id = report["task_id"]
                agent_id = report["agent_id"]
                # Store with composite key to keep all agent evaluations of the same task
                composite_key = f"{task_id}_{agent_id}"
                self._reports_by_task[composite_key] = report
                # Append to agent history (dedupe by evaluated_at for the task)
                self._reports_by_agent.setdefault(agent_id, [])
                existing_agent = self._reports_by_agent[agent_id]
                if not any((r.get("task_id") == task_id and r.get("evaluated_at") == report.get("evaluated_at")) for r in existing_agent):
                    existing_agent.append(report)
                # Append to task history
                self._history_by_task.setdefault(task_id, [])
                existing_task = self._history_by_task[task_id]
                if not any(r.get("evaluated_at") == report.get("evaluated_at") for r in existing_task):
                    existing_task.append(report)
                    # Persist incrementally
                    try:
                        self.store.append(report)
                    except Exception as e:
                        self.logger.error(json.dumps({"event": "history_append_error", "task_id": task_id, "error": str(e)}))
                total_reports += 1
        self.logger.info(json.dumps({"event": "evaluate_all_done", "tasks": len(data_list), "reports": total_reports}))

    def get_task_report(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self._reports_by_task.get(str(task_id))

    def get_agent_reports(self, agent_id: str) -> List[Dict[str, Any]]:
        return self._reports_by_agent.get(str(agent_id), [])

    def get_all_reports(self) -> List[Dict[str, Any]]:
        return list(self._reports_by_task.values())

    def get_task_history(self, task_id: str) -> List[Dict[str, Any]]:
        return list(self._history_by_task.get(str(task_id), []))
