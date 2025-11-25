import { useState, useEffect } from 'react';
import { API_BASE } from '../config';


const ScoreBreakdown = ({ scores, metrics, penalties, summary, isCompact = false }) => {
  const metricsList = [
    { key: 'correctness', label: 'Correctness' },
    { key: 'efficiency', label: 'Efficiency' },
    { key: 'quality', label: 'Quality' },
    { key: 'stability', label: 'Stability' },
    { key: 'autonomy', label: 'Autonomy' },
    { key: 'resource_efficiency', label: 'Resource Efficiency' },
  ];

  // If compact, use fewer columns
  const gridStyle = isCompact 
    ? { gridTemplateColumns: '1fr', gap: '12px' } 
    : { gridTemplateColumns: '1fr 1fr', gap: '24px' };

  return (
    <div className="evaluation-details" style={isCompact ? { padding: '16px 0 0 0', background: 'transparent', borderTop: 'none' } : {}}>
      <h4 className="details-header">Score Breakdown</h4>
      <div className="details-grid" style={gridStyle}>
        {metricsList.map(({ key, label }) => {
          let val = scores?.[key] || 0;
          // Normalize: if > 1, assume it's already a percentage
          const normalized = val > 1 ? val / 100 : val;
          const percent = (normalized * 100).toFixed(1);
          return (
            <div className="detail-metric" key={key}>
              <span className="label">{label}</span>
              <div className="bar-container">
                <div className="bar" style={{ width: `${Math.min(normalized * 100, 100)}%` }} />
              </div>
              <span className="value">{percent}%</span>
            </div>
          );
        })}
      </div>

      {metrics && (
         <div className="metrics-section" style={{ marginTop: '1rem', padding: '1rem', background: 'rgba(255,255,255,0.05)', borderRadius: '6px' }}>
             <h4 className="details-header" style={{ marginBottom: '0.5rem' }}>Raw Metrics</h4>
             <div style={{ display: 'grid', gridTemplateColumns: isCompact ? '1fr' : '1fr 1fr', gap: '0.5rem', fontSize: '0.85rem', color: '#fff' }}>
                <div>Time: <span style={{ color: '#fff' }}>{metrics.completion_time_s?.toFixed(1)}s</span></div>
                <div>Errors: <span style={{ color: '#fff' }}>{metrics.error_count}</span></div>
                <div>API Calls: <span style={{ color: '#fff' }}>{metrics.total_api_calls}</span></div>
                <div>Cost: <span style={{ color: '#fff' }}>${metrics.cost_usd?.toFixed(4)}</span></div>
             </div>
         </div>
      )}
      
      {penalties && Object.keys(penalties).length > 0 && Object.values(penalties).some(v => v > 0) && (
        <div className="penalties-section" style={{ marginTop: '1rem' }}>
            <h4 className="details-header" style={{ color: '#ef4444' }}>Penalties Applied</h4>
            <ul style={{ fontSize: '0.85rem', color: '#ef4444', paddingLeft: '1.2rem', margin: 0 }}>
                {Object.entries(penalties).map(([k, v]) => (
                    v > 0 && <li key={k}>{k.replace(/_/g, ' ')}: -{(v * 100).toFixed(1)}%</li>
                ))}
            </ul>
        </div>
      )}

      <div className="feedback-section" style={{ marginTop: '1rem' }}>
         <div className="label">Summary</div>
         <p>{summary || 'No specific feedback provided.'}</p>
      </div>
    </div>
  );
};

const EvaluationItem = ({ evaluation }) => {
  const [expanded, setExpanded] = useState(false);
  
  // Handle both unified structure and potentially flat structure if API varies
  const score = evaluation.scores?.overall_score || evaluation.scores?.final_score || 0;
  // Convert to percentage if needed (heuristically)
  const displayScore = score <= 1 ? score * 100 : score;
  
  const scoreColor = displayScore >= 70 ? '#22c55e' : displayScore >= 40 ? '#f59e0b' : '#ef4444';

  return (
    <div className="evaluation-wrapper">
      <div className="evaluation-item" onClick={() => setExpanded(!expanded)}>
        <div className="evaluation-item__main">
          <div className="evaluation-id">Task #{evaluation.task_id}</div>
          <div className="evaluation-agent">{evaluation.agent_id}</div>
          <div className="evaluation-date">
            {evaluation.evaluated_at && new Date(evaluation.evaluated_at).toLocaleString()}
          </div>
        </div>
        <div className="evaluation-item__score">
          <div className="score-badge" style={{ color: scoreColor, borderColor: scoreColor }}>
            {displayScore.toFixed(0)}%
          </div>
          <div className={`chevron ${expanded ? 'expanded' : ''}`}>▼</div>
        </div>
      </div>
      
      {expanded && (
        <ScoreBreakdown 
            scores={evaluation.scores}
            metrics={evaluation.metrics}
            penalties={evaluation.penalties}
            summary={evaluation.evaluation_summary}
        />
      )}
    </div>
  );
};

const EvaluatorView = () => {
  const [evaluatorData, setEvaluatorData] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [progressGraph, setProgressGraph] = useState(null);
  const [graphLoading, setGraphLoading] = useState(false);
  
  // Track expanded state for agent sidebar items
  const [expandedAgents, setExpandedAgents] = useState({});

  useEffect(() => {
    const fetchEvaluatorData = async () => {
      try {
        const response = await fetch(`${API_BASE}/evaluator/status`);
        if (response.ok) {
          const data = await response.json();
          setEvaluatorData(data);
        }
      } catch (err) {
        // Silently fail
      } finally {
        setIsLoading(false);
      }
    };

    const fetchProgressGraph = async () => {
      try {
        setGraphLoading(true);
        const response = await fetch(`${API_BASE}/evaluator/agents/progress/graph`);
        if (response.ok) {
          const data = await response.json();
          if (data.image_data_url) {
            setProgressGraph(data);
          }
        }
      } catch (err) {
        console.error('Error fetching graph:', err);
      } finally {
        setGraphLoading(false);
      }
    };

    fetchEvaluatorData();
    fetchProgressGraph();
    
    const statusInterval = setInterval(fetchEvaluatorData, 10000);
    const graphInterval = setInterval(fetchProgressGraph, 30000);

    return () => {
      clearInterval(statusInterval);
      clearInterval(graphInterval);
    };
  }, []);

  const toggleAgent = (agentId) => {
      setExpandedAgents(prev => ({
          ...prev,
          [agentId]: !prev[agentId]
      }));
  };

  const status = evaluatorData?.status || 'loading';
  const stats = {
    totalEvaluations: evaluatorData?.total_evaluations || 0,
    agentsEvaluated: evaluatorData?.agents_evaluated || 0,
    tasksEvaluated: evaluatorData?.tasks_evaluated || 0,
    averageScore: evaluatorData?.average_score || 0,
  };
  const agentScores = evaluatorData?.agent_scores || {};
  const recentEvaluations = evaluatorData?.recent_evaluations || [];

  return (
    <div className="evaluator-view">
      <div className="evaluator-header">
        <div>
          <h1>Evaluator Dashboard</h1>
          <p>Real-time performance monitoring</p>
        </div>
        <div className={`system-status ${status === 'running' ? 'active' : ''}`}>
            <span className="status-dot"></span>
            {status === 'running' ? 'System Active' : 'System Idle'}
        </div>
      </div>

      <div className="dashboard-grid">
        <div className="dashboard-main">
            <div className="evaluator-card">
                <div className="card-header">
                    <h3>Agent Progress Graph</h3>
                </div>
                <div className="card-body graph-body">
                    {graphLoading && !progressGraph ? (
                    <div className="placeholder-state">Loading graph...</div>
                    ) : progressGraph?.image_data_url ? (
                    <div className="graph-container">
                        <img 
                        src={progressGraph.image_data_url} 
                        alt="Agent Progress Graph" 
                        />
                        <div className="graph-caption">
                        {progressGraph.message}
                        </div>
                    </div>
                    ) : (
                    <div className="placeholder-state">
                        No graph data available yet.
                    </div>
                    )}
                </div>
            </div>

            <div className="stats-banner">
              <div className="stats-banner__item">
                <span className="stats-banner__label">Total Evaluations</span>
                <span className="stats-banner__value">{stats.totalEvaluations}</span>
              </div>
              <div className="stats-banner__item">
                <span className="stats-banner__label">Agents Monitored</span>
                <span className="stats-banner__value">{stats.agentsEvaluated}</span>
              </div>
              <div className="stats-banner__item">
                <span className="stats-banner__label">Tasks Processed</span>
                <span className="stats-banner__value">{stats.tasksEvaluated}</span>
              </div>
              <div className="stats-banner__item">
                <span className="stats-banner__label">Avg. Success Rate</span>
                <span className="stats-banner__value">{stats.averageScore.toFixed(1)}%</span>
              </div>
            </div>
        </div>

        <div className="dashboard-sidebar">
            <div className="evaluator-card">
                <div className="card-header">
                    <h3>Performance by Agent</h3>
                </div>
                <div className="card-body">
                    {['agent1', 'agent2', 'agent3'].map(agentId => {
                        const data = agentScores[agentId];
                        const score = data?.score || 0;
                        const color = score >= 70 ? '#22c55e' : score >= 40 ? '#f59e0b' : '#ef4444';
                        const isExpanded = expandedAgents[agentId];
                        
                        return (
                            <div 
                                className={`agent-performance-item ${data ? 'clickable' : ''}`} 
                                key={agentId}
                                onClick={() => data && toggleAgent(agentId)}
                                style={{ cursor: data ? 'pointer' : 'default' }}
                            >
                                <div className="perf-header">
                                    <span className="perf-name">{agentId}</span>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                        <span className="perf-score" style={{ color }}>{score.toFixed(1)}%</span>
                                        {data && <span className={`chevron ${isExpanded ? 'expanded' : ''}`}>▼</span>}
                                    </div>
                                </div>
                                <div className="perf-bar-bg">
                                    <div className="perf-bar-fill" style={{ 
                                        width: `${score}%`,
                                        backgroundColor: color
                                    }}></div>
                                </div>
                                
                                <div className={`agent-details-dropdown ${isExpanded ? 'expanded' : ''}`}>
                                    <div className="agent-details-content">
                                         {data && (
                                             <ScoreBreakdown 
                                                scores={data.breakdown}
                                                metrics={data.metrics}
                                                penalties={data.penalties}
                                                summary={data.summary}
                                                isCompact={true}
                                             />
                                         )}
                                    </div>
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>

            <div className="evaluator-card evaluator-card--compact">
                <div className="card-header card-header--compact">
                    <h3>Recent Evaluations</h3>
                </div>
                <div className="card-body no-padding">
                    {recentEvaluations.length === 0 ? (
                    <div className="placeholder-state placeholder-state--compact">
                        No evaluations yet.
                    </div>
                    ) : (
                    <div className="evaluations-list evaluations-list--compact">
                        {recentEvaluations.slice(0, 3).map((evaluation, idx) => (
                        <EvaluationItem key={idx} evaluation={evaluation} />
                        ))}
                    </div>
                    )}
                </div>
            </div>
        </div>
      </div>
    </div>
  );
};

export default EvaluatorView;