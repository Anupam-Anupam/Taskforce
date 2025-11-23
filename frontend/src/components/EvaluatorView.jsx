import { useState, useEffect } from 'react';
import { API_BASE } from '../config';

const EvaluatorView = () => {
  const [evaluatorData, setEvaluatorData] = useState(null);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    const fetchEvaluatorData = async () => {
      try {
        // Placeholder - replace with actual evaluator API endpoint when available
        const response = await fetch(`${API_BASE}/evaluator/status`);
        if (response.ok) {
          const data = await response.json();
          setEvaluatorData(data);
        }
        // Silently fail if endpoint doesn't exist yet
      } catch (err) {
        // Silently fail - evaluator endpoint not yet implemented
      } finally {
        setIsLoading(false);
      }
    };

    fetchEvaluatorData();
    const interval = setInterval(fetchEvaluatorData, 10000); // Refresh every 10s

    return () => clearInterval(interval);
  }, []);

  return (
    <div className="evaluator-view">
      <div className="evaluator-header">
        <h1>Evaluator Dashboard</h1>
        <p>Monitor agent performance and evaluation metrics</p>
      </div>

      <div className="evaluator-grid">
        {/* Placeholder cards for evaluator metrics */}
        <div className="evaluator-card">
          <div className="evaluator-card__header">
            <h3>📊 Performance Metrics</h3>
          </div>
          <div className="evaluator-card__body">
            <div className="metric-row">
              <span className="metric-label">Success Rate</span>
              <span className="metric-value">—</span>
            </div>
            <div className="metric-row">
              <span className="metric-label">Avg. Task Time</span>
              <span className="metric-value">—</span>
            </div>
            <div className="metric-row">
              <span className="metric-label">Tasks Completed</span>
              <span className="metric-value">—</span>
            </div>
          </div>
        </div>

        <div className="evaluator-card">
          <div className="evaluator-card__header">
            <h3>🎯 Agent Scores</h3>
          </div>
          <div className="evaluator-card__body">
            <div className="agent-score">
              <span className="agent-name">🤖 Agent 1</span>
              <div className="score-bar">
                <div className="score-fill" style={{ width: '0%' }}></div>
              </div>
              <span className="score-value">—</span>
            </div>
            <div className="agent-score">
              <span className="agent-name">🦾 Agent 2</span>
              <div className="score-bar">
                <div className="score-fill" style={{ width: '0%' }}></div>
              </div>
              <span className="score-value">—</span>
            </div>
            <div className="agent-score">
              <span className="agent-name">🧠 Agent 3</span>
              <div className="score-bar">
                <div className="score-fill" style={{ width: '0%' }}></div>
              </div>
              <span className="score-value">—</span>
            </div>
          </div>
        </div>

        <div className="evaluator-card evaluator-card--wide">
          <div className="evaluator-card__header">
            <h3>📈 Recent Evaluations</h3>
          </div>
          <div className="evaluator-card__body">
            <div style={{ 
              color: 'var(--muted-text)', 
              textAlign: 'center',
              padding: '40px 20px'
            }}>
              No evaluation data available yet. Evaluations will appear here once agents complete tasks.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default EvaluatorView;

