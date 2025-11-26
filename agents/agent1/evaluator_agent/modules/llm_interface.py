import os
import logging
from typing import Any, Dict, List, Optional

import requests


class LLMInterface:
    """Minimal LLM interface for generating evaluation summaries.

    Uses a hypothetical GPT-5 reasoning API with an OpenAI-compatible endpoint if available.
    Set env: GPT5_API_BASE, GPT5_API_KEY, GPT5_MODEL
    Fallback: produce a rule-based short summary if API not configured.
    """

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self.api_base = os.getenv("GPT5_API_BASE", "https://api.openai.com/v1")
        self.api_key = os.getenv("GPT5_API_KEY")
        self.model = os.getenv("GPT5_MODEL", "gpt-5-reasoning")

    def summarize(self, task: Dict[str, Any]) -> str:
        if not self.api_key:
            return self._fallback_summary(task)

        logs: List[Dict[str, Any]] = task.get("logs", [])
        sample = "\n".join([f"[{l.get('timestamp')}] {l.get('level')}: {str(l.get('message'))[:200]}" for l in logs[-50:]])
        m = task.get("metrics", {})
        prompt = (
            "You are an evaluator of an autonomous agent. Summarize the agent's performance, correctness, autonomy behavior, and notable events.\n"
            f"Metrics: {m}\n"
            f"Recent logs:\n{sample}\n"
            "Provide a concise, objective assessment."
        )
        try:
            resp = requests.post(
                f"{self.api_base}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": "You are a precise evaluation summarizer."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 300,
                },
                timeout=20,
            )
            if resp.ok:
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content")
                return content or self._fallback_summary(task)
        except Exception:
            pass
        return self._fallback_summary(task)

    def evaluate_correctness(self, initial_request: str, final_output: str) -> float:
        """
        Evaluate correctness by comparing initial request with final output.
        
        Args:
            initial_request: The original user request/task description
            final_output: The agent's final output/result
            
        Returns:
            Correctness score between 0.0 and 1.0
        """
        if not initial_request or not final_output:
            return 0.0
        
        if not self.api_key:
            # Fallback: simple heuristic based on length and keyword matching
            return self._fallback_correctness(initial_request, final_output)
        
        prompt = (
            "You are an evaluator assessing how well an agent's output aligns with the original request.\n\n"
            f"Original Request:\n{initial_request}\n\n"
            f"Agent's Final Output:\n{final_output}\n\n"
            "Evaluate how correctly the final output addresses and fulfills the original request.\n\n"
            "Scoring Guidelines (use a DECIMAL between 0.0 and 1.0, NOT a percentage):\n"
            "- 1.0 (perfect): Output fully addresses the request with complete accuracy\n"
            "- 0.8-0.9 (excellent): Output addresses most of the request with minor gaps\n"
            "- 0.6-0.7 (good): Output addresses the core request but may have some issues\n"
            "- 0.4-0.5 (fair): Output partially addresses the request with notable gaps\n"
            "- 0.2-0.3 (poor): Output has some relevance but misses key requirements\n"
            "- 0.0-0.1 (very poor): Output has little or no relevance to the request\n\n"
            "Important: Be lenient - if the output makes a reasonable attempt to address the request, "
            "even if imperfect, give it at least 0.3. Only use very low scores (0.0-0.2) if the output "
            "is completely unrelated or shows no understanding of the request.\n\n"
            "Respond with ONLY a decimal number between 0.0 and 1.0 (e.g., 0.75, not 75 or 75%). "
            "Do not include any explanation, just the number."
        )
        
        try:
            resp = requests.post(
                f"{self.api_base}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": "You are a precise correctness evaluator. Respond with only a number between 0.0 and 1.0."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 10,
                },
                timeout=30,
            )
            if resp.ok:
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                
                # Extract number from response - handle various formats
                import re
                score = None
                
                # Try direct float conversion first
                try:
                    score = float(content)
                except ValueError:
                    # Try to extract number from text (handles "2%", "score: 2", etc.)
                    # Look for numbers with optional decimal points
                    match = re.search(r'([0-9]+(?:\.[0-9]+)?)', content)
                    if match:
                        try:
                            score = float(match.group(1))
                        except ValueError:
                            pass
                
                if score is not None:
                    # If score > 1.0, assume it's a percentage and convert to 0-1 scale
                    if score > 1.0:
                        score = score / 100.0
                        self.logger.info(f"Converted percentage score {score * 100}% to decimal {score}")
                    
                    # Clamp to valid range
                    score = max(0.0, min(1.0, score))
                    self.logger.info(f"LLM correctness score: {score} (from response: '{content[:50]}...')")
                    return score
                else:
                    self.logger.warning(f"Could not parse score from LLM response: '{content[:100]}'")
        except Exception as e:
            self.logger.warning(f"LLM correctness evaluation failed: {e}")
        
        return self._fallback_correctness(initial_request, final_output)
    
    def _fallback_correctness(self, initial_request: str, final_output: str) -> float:
        """Fallback correctness evaluation using simple heuristics."""
        if not initial_request:
            # If no request, can't evaluate - but if there's output, give some credit
            return 0.3 if final_output else 0.0
        
        if not final_output:
            return 0.0
        
        # Simple keyword matching and length-based heuristic
        request_lower = initial_request.lower()
        output_lower = final_output.lower()
        
        # Remove common stop words for better matching
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were', 'be', 'been', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'should', 'could', 'may', 'might', 'must', 'can'}
        
        # Count matching keywords (more lenient - use word stems and ignore stop words)
        request_words = set(word for word in request_lower.split() if word not in stop_words and len(word) > 2)
        output_words = set(word for word in output_lower.split() if word not in stop_words and len(word) > 2)
        
        if len(request_words) == 0:
            # If request has no meaningful words, give baseline score for any output
            return 0.4 if final_output else 0.0
        
        common_words = request_words.intersection(output_words)
        keyword_match_ratio = len(common_words) / len(request_words)
        
        # Length similarity (output shouldn't be too short relative to request)
        # More lenient - accept outputs that are at least 20% of request length
        min_output_length = max(10, len(initial_request) * 0.2)
        if len(final_output) < min_output_length:
            length_penalty = 0.3
        else:
            length_ratio = min(1.0, len(final_output) / max(1, len(initial_request)))
            length_penalty = 1.0 - (1.0 - length_ratio) * 0.3  # Less penalty for length differences
        
        # Combined score with more weight on keyword matching
        score = 0.7 * keyword_match_ratio + 0.3 * length_penalty
        
        # Ensure minimum baseline: if there's any output and any keyword match, give at least 0.3
        if len(common_words) > 0 and len(final_output) > 0:
            score = max(0.3, score)
        
        return max(0.0, min(1.0, score))

    def _fallback_summary(self, task: Dict[str, Any]) -> str:
        m = task.get("metrics", {})
        return (
            "Evaluation summary based on heuristics: "
            f"completion_time={m.get('completion_time_s', 0.0)}s, "
            f"errors={m.get('error_count', 0)}, retries={m.get('retry_count', 0)}, "
            f"dependency_requests={m.get('human_or_agent_requests', 0)}, api_calls={m.get('total_api_calls', 0)}."
        )

    def generate_structured_feedback(self, agent_id: str, reports: List[Dict[str, Any]], task_data_list: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Generate structured feedback for an agent by directly asking the LLM what the agent succeeded in,
        what it struggled with, and recommendations for improvement.
        
        Args:
            agent_id: The agent identifier
            reports: List of evaluation reports (for score calculation)
            task_data_list: Optional list of full task data (logs, initial_request, final_output) for LLM analysis
        
        Returns:
            Dict with keys: strengths, weaknesses, recommendations, overall_assessment
        """
        if not reports:
            return {
                "score": 0,
                "assessment": "poor",
                "strengths": [],
                "weaknesses": [],
                "recommendations": [],
                "overall_assessment": "No evaluation data available for this agent."
            }
        
        # Aggregate metrics and scores
        total_tasks = len(reports)
        avg_score = sum(r.get("scores", {}).get("final_score", 0) for r in reports) / total_tasks if total_tasks > 0 else 0
        if avg_score <= 1.0:
            avg_score *= 100
        
        # Determine assessment word based on score benchmarks
        def get_assessment_word(score):
            if score >= 90:
                return "perfect"
            elif score >= 80:
                return "excellent"
            elif score >= 60:
                return "good"
            elif score >= 40:
                return "fair"
            else:
                return "poor"
        
        assessment_word = get_assessment_word(avg_score)
        
        total_errors = sum(r.get("metrics", {}).get("error_count", 0) for r in reports)
        total_time = sum(r.get("metrics", {}).get("completion_time_s", 0) for r in reports)
        avg_time = total_time / total_tasks if total_tasks > 0 else 0
        total_cost = sum(r.get("metrics", {}).get("cost_usd", 0) for r in reports)
        
        # Get recent summaries
        recent_summaries = [r.get("evaluation_summary", "") for r in reports[-3:]]
        
        if not self.api_key:
            return self._fallback_feedback(agent_id, avg_score, total_errors, avg_time, total_cost)
        
        # Build context from task data if available, otherwise use reports
        task_context = ""
        if task_data_list and len(task_data_list) > 0:
            # Use actual task data (logs, requests, outputs) for analysis
            context_parts = []
            for idx, task_data in enumerate(task_data_list[:5]):  # Limit to 5 most recent tasks
                initial_request = task_data.get("initial_request", "")
                final_output = task_data.get("final_output", "")
                logs = task_data.get("logs", [])
                
                # Sample recent logs (last 20)
                log_sample = "\n".join([
                    f"[{l.get('level', 'INFO')}] {str(l.get('message', ''))[:150]}"
                    for l in logs[-20:]
                ])
                
                context_parts.append(
                    f"Task {idx + 1}:\n"
                    f"Initial Request: {initial_request[:500]}\n"
                    f"Final Output: {final_output[:500]}\n"
                    f"Recent Logs:\n{log_sample[:1000]}\n"
                )
            task_context = "\n\n".join(context_parts)
        elif recent_summaries:
            # Fallback: use evaluation summaries from reports
            task_context = "Recent Evaluation Summaries:\n" + "\n".join([f"- {s}" for s in recent_summaries if s])
        
        # If no context available, provide basic metrics as context
        if not task_context:
            task_context = (
                f"Performance Metrics:\n"
                f"- Average Score: {avg_score:.1f}%\n"
                f"- Total Tasks: {total_tasks}\n"
                f"- Total Errors: {total_errors}\n"
                f"- Average Time: {avg_time:.1f}s\n"
                f"- Total Cost: ${total_cost:.4f}\n"
            )
            self.logger.warning(f"Limited context available for {agent_id}, using basic metrics")
        
        prompt = (
            f"You are analyzing the performance of {agent_id}, an autonomous AI agent.\n\n"
            f"Based on the following task execution data, please provide direct feedback:\n\n"
            f"{task_context}\n\n"
            f"Please analyze this agent's performance and answer these questions directly:\n\n"
            f"1. What did this agent SUCCEED in? What did it do well?\n"
            f"2. What did this agent STRUGGLE with? Where did it face challenges or fail?\n"
            f"3. What are your RECOMMENDATIONS for improving this agent? Focus specifically on:\n"
            f"   - How to fine-tune or adjust the system prompts (e.g., 'Modify system prompt to emphasize X', 'Add clarification in system prompt about Y')\n"
            f"   - How to fine-tune the model itself (e.g., 'Adjust model temperature/sampling parameters', 'Consider fine-tuning on specific task types')\n"
            f"   - Be specific and actionable about prompt engineering and model configuration\n\n"
            f"Provide your response in JSON format with these exact keys:\n"
            f'{{"strengths": ["what the agent succeeded in 1", "what the agent succeeded in 2"], '
            f'"weaknesses": ["what the agent struggled with 1", "what the agent struggled with 2"], '
            f'"recommendations": ["specific recommendation 1", "specific recommendation 2"], '
            f'"overall_assessment": "one sentence summary starting with the agent name, e.g. \\"{agent_id} has a moderate performance score of {avg_score:.1f}%\\""}}\n\n'
            f"Be direct, specific, and actionable. Base your analysis on the actual task execution data provided. "
            f"Return ONLY valid JSON, no other text."
        )
        
        try:
            self.logger.info(f"Calling LLM for structured feedback for {agent_id} with API base: {self.api_base}")
            # Build request payload
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "You are a performance evaluator. Respond with only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 800,
            }
            # Only add response_format if the model supports it (OpenAI GPT-4+)
            if "gpt-4" in self.model.lower() or "gpt-3.5" in self.model.lower():
                payload["response_format"] = {"type": "json_object"}
            
            resp = requests.post(
                f"{self.api_base}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=60,
            )
            if resp.ok:
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                import json
                try:
                    feedback = json.loads(content)
                    # Ensure all required keys exist
                    self.logger.info(f"Successfully generated LLM feedback for {agent_id}")
                    return {
                        "score": round(avg_score, 1),
                        "assessment": assessment_word,
                        "strengths": feedback.get("strengths", []),
                        "weaknesses": feedback.get("weaknesses", []),
                        "recommendations": feedback.get("recommendations", []),
                        "overall_assessment": feedback.get("overall_assessment", "No assessment available.")
                    }
                except json.JSONDecodeError as e:
                    self.logger.error(f"Failed to parse feedback JSON for {agent_id}: {e}. Content: {content[:200]}")
            else:
                self.logger.error(f"LLM API call failed for {agent_id}: {resp.status_code} - {resp.text[:200]}")
        except Exception as e:
            self.logger.error(f"Failed to generate structured feedback for {agent_id}: {e}", exc_info=True)
        
        # Only use fallback if LLM call actually failed
        self.logger.warning(f"Using fallback feedback for {agent_id} due to LLM failure")
        return self._fallback_feedback(agent_id, avg_score, total_errors, avg_time, total_cost)
    
    def _fallback_feedback(self, agent_id: str, avg_score: float, total_errors: int, avg_time: float, total_cost: float) -> Dict[str, Any]:
        """Fallback structured feedback using heuristics."""
        # Determine assessment word based on score benchmarks
        def get_assessment_word(score):
            if score >= 90:
                return "perfect"
            elif score >= 80:
                return "excellent"
            elif score >= 60:
                return "good"
            elif score >= 40:
                return "fair"
            else:
                return "poor"
        
        assessment_word = get_assessment_word(avg_score)
        strengths = []
        weaknesses = []
        recommendations = []
        
        if avg_score >= 80:
            strengths.append("High average performance score")
        elif avg_score < 60:
            weaknesses.append("Below average performance score")
        
        if total_errors == 0:
            strengths.append("No errors recorded")
        elif total_errors > 5:
            weaknesses.append(f"High error count ({total_errors})")
            recommendations.append("Focus on error reduction and debugging")
        
        if avg_time < 60:
            strengths.append("Fast task completion")
        elif avg_time > 300:
            weaknesses.append("Slow task completion times")
            recommendations.append("Optimize task execution efficiency")
        
        if total_cost < 0.10:
            strengths.append("Cost-efficient operations")
        elif total_cost > 1.0:
            weaknesses.append("High operational costs")
            recommendations.append("Review and optimize API usage to reduce costs")
        
        if not strengths:
            strengths.append("Agent is operational")
        
        if not weaknesses:
            weaknesses.append("No significant issues identified")
        
        if not recommendations:
            recommendations.append("Continue monitoring performance")
        
        return {
            "score": round(avg_score, 1),
            "assessment": assessment_word,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "recommendations": recommendations,
            "overall_assessment": f"{agent_id} shows {'strong' if avg_score >= 70 else 'moderate' if avg_score >= 50 else 'weak'} performance with an average score of {avg_score:.1f}%."
        }
