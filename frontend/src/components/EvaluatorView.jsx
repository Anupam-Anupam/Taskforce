import { useState, useEffect } from 'react';
import { API_BASE } from '../config';


const ScoreBreakdown = ({ scores, metrics, penalties, summary, isCompact = false, isCompleted = false }) => {
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
          let normalized = val > 1 ? val / 100 : val;
          
          // For completed tasks, correctness should be at least 80% + evaluator's score (capped at 100%)
          if (key === 'correctness' && isCompleted) {
            const evaluatorScore = normalized;
            normalized = Math.min(1.0, 0.8 + evaluatorScore); // 80% + evaluator's score, capped at 100%
          }
          
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

      <div className="metrics-section" style={{ marginTop: '1rem', padding: '1rem', background: 'rgba(255,255,255,0.05)', borderRadius: '6px' }}>
          <h4 className="details-header" style={{ marginBottom: '0.5rem' }}>Raw Metrics</h4>
          <div style={{ display: 'grid', gridTemplateColumns: isCompact ? '1fr' : '1fr 1fr', gap: '0.5rem', fontSize: '0.85rem', color: '#fff' }}>
             <div>Time: <span style={{ color: '#fff' }}>{(metrics?.completion_time_s ?? 0).toFixed(1)}s</span></div>
             <div>Errors: <span style={{ color: '#fff' }}>{metrics?.error_count ?? 0}</span></div>
             <div>API Calls: <span style={{ color: '#fff' }}>{metrics?.total_api_calls ?? 0}</span></div>
             <div>Cost: <span style={{ color: '#fff' }}>${(metrics?.cost_usd ?? 0).toFixed(4)}</span></div>
          </div>
      </div>
      
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
  const initialRequest = evaluation.initial_request || evaluation.task_title || '';

  return (
    <div className="evaluation-wrapper">
      <div className="evaluation-item" onClick={() => setExpanded(!expanded)}>
        <div className="evaluation-item__main">
          <div className="evaluation-id">Task #{evaluation.task_id}</div>
          <div className="evaluation-agent">{evaluation.agent_id}</div>
          {initialRequest && (
            <div style={{ 
              fontSize: '0.85rem', 
              color: 'var(--muted-text)', 
              marginTop: '4px',
              lineHeight: '1.4',
              ...(expanded ? {} : {
                display: '-webkit-box',
                WebkitLineClamp: 2,
                WebkitBoxOrient: 'vertical',
                overflow: 'hidden',
                textOverflow: 'ellipsis'
              })
            }}>
              {initialRequest}
            </div>
          )}
          {evaluation.metrics && (
            <div style={{ 
              display: 'flex', 
              gap: '12px', 
              marginTop: '8px',
              fontSize: '0.75rem',
              color: 'var(--lighter-text)'
            }}>
              {evaluation.metrics.completion_time_s && (
                <span>⏱ {evaluation.metrics.completion_time_s.toFixed(1)}s</span>
              )}
              {evaluation.metrics.error_count !== undefined && (
                <span>⚠ {evaluation.metrics.error_count}</span>
              )}
              {evaluation.metrics.total_api_calls && (
                <span>📞 {evaluation.metrics.total_api_calls}</span>
              )}
            </div>
          )}
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
      
    </div>
  );
};

const EvaluatorView = () => {
  const [evaluatorData, setEvaluatorData] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [progressGraph, setProgressGraph] = useState(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [isGraphExpanded, setIsGraphExpanded] = useState(false);
  
  // Track expanded state for agent sidebar items
  const [expandedAgents, setExpandedAgents] = useState({});
  // Track expanded state for feedback cards
  const [expandedFeedback, setExpandedFeedback] = useState({});

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

  // Close expanded graph on Escape key
  useEffect(() => {
    if (!isGraphExpanded) return;
    const handleEscape = (e) => {
      if (e.key === 'Escape') {
        setIsGraphExpanded(false);
      }
    };
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [isGraphExpanded]);

  const toggleAgent = (agentId) => {
      setExpandedAgents(prev => ({
          ...prev,
          [agentId]: !prev[agentId]
      }));
  };

  const toggleFeedback = (agentId) => {
      setExpandedFeedback(prev => ({
          ...prev,
          [agentId]: !prev[agentId]
      }));
  };

  const status = evaluatorData?.status || 'loading';
  const agentScores = evaluatorData?.agent_scores || {};
  const agentFeedback = evaluatorData?.agent_feedback || {};
  const recentEvaluations = evaluatorData?.recent_evaluations || [];
  
  // Calculate average score from agent feedback summaries
  const calculateAverageFromFeedback = () => {
    const scores = [];
    ['agent1', 'agent2', 'agent3'].forEach(agentId => {
      const feedback = agentFeedback[agentId];
      if (feedback?.score !== undefined) {
        scores.push(feedback.score);
      }
    });
    return scores.length > 0 ? scores.reduce((a, b) => a + b, 0) / scores.length : 0;
  };
  
  const stats = {
    totalEvaluations: evaluatorData?.total_evaluations || 0,
    agentsEvaluated: evaluatorData?.agents_evaluated || 0,
    tasksEvaluated: evaluatorData?.tasks_evaluated || 0,
    averageScore: calculateAverageFromFeedback(),
  };

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
                        onClick={() => setIsGraphExpanded(true)}
                        style={{ cursor: 'pointer', transition: 'transform 0.2s' }}
                        onMouseEnter={(e) => e.target.style.transform = 'scale(1.02)'}
                        onMouseLeave={(e) => e.target.style.transform = 'scale(1)'}
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
                <span className="stats-banner__value">{isNaN(stats.averageScore) ? '0.0' : stats.averageScore.toFixed(1)}%</span>
                </div>
            </div>

            <div className="evaluator-card">
                <div className="card-header">
                    <h3>Agent Feedback</h3>
                </div>
                <div className="card-body">
                    {['agent1', 'agent2', 'agent3'].map(agentId => {
                        const feedback = agentFeedback[agentId];
                        const isExpanded = expandedFeedback[agentId];
                        const agentLabels = {
                            'agent1': 'Agent 1 - GPT4',
                            'agent2': 'Agent 2 - GPT 5',
                            'agent3': 'Agent 3 - GPT 4.1'
                        };
                        
                        if (!feedback) {
                            return (
                                <div key={agentId} style={{ marginBottom: '24px' }}>
                                    <div style={{ color: 'var(--muted-text)', fontSize: '0.9rem' }}>
                                        No feedback available yet.
                                    </div>
                                </div>
                            );
                        }
                        
                        const score = feedback.score || 0;
                        const assessment = feedback.assessment || 'poor';
                        const scoreColor = score >= 90 ? '#22c55e' : score >= 80 ? '#22c55e' : score >= 60 ? '#f59e0b' : score >= 40 ? '#f59e0b' : '#ef4444';
                        
                        return (
                            <div 
                                key={agentId} 
                                style={{ 
                                    marginBottom: '16px', 
                                    padding: '16px', 
                                    background: 'rgba(255, 255, 255, 0.02)',
                                    borderRadius: '12px',
                                    border: '1px solid var(--border-soft)',
                                    transition: 'background 0.2s'
                                }}
                                onMouseEnter={() => setExpandedFeedback(prev => ({ ...prev, [agentId]: true }))}
                                onMouseLeave={() => setExpandedFeedback(prev => ({ ...prev, [agentId]: false }))}
                            >
                                <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: isExpanded ? '16px' : '0' }}>
                                    <div style={{
                                        width: '60px',
                                        height: '60px',
                                        borderRadius: '50%',
                                        background: `radial-gradient(circle, ${scoreColor}, ${scoreColor}dd)`,
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'center',
                                        flexShrink: 0,
                                        boxShadow: `0 0 20px ${scoreColor}40, 0 0 40px ${scoreColor}20`,
                                        border: `2px solid ${scoreColor}60`
                                    }}>
                                        <span style={{
                                            fontSize: '1rem',
                                            fontWeight: 700,
                                            color: '#fff',
                                            textShadow: '0 1px 2px rgba(0,0,0,0.3)'
                                        }}>
                                            {score.toFixed(0)}%
                                        </span>
                                    </div>
                                    <div style={{ flex: 1 }}>
                                        <div style={{ marginBottom: '6px' }}>
                                            <h4 style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--text-color)' }}>
                                                {agentLabels[agentId] || agentId}
                                            </h4>
                                        </div>
                                        <div style={{ fontSize: '0.9rem', color: 'var(--muted-text)' }}>
                                            {assessment.charAt(0).toUpperCase() + assessment.slice(1)} Performance
                                        </div>
                                    </div>
                                </div>
                                
                                <div 
                                    style={{
                                        display: 'grid',
                                        gridTemplateRows: isExpanded ? '1fr' : '0fr',
                                        transition: 'grid-template-rows 0.3s ease-out',
                                        overflow: 'hidden'
                                    }}
                                >
                                    <div style={{ minHeight: 0, overflow: 'hidden' }}>
                                        <div style={{ paddingTop: '16px', borderTop: '1px solid var(--border-soft)' }}>
                                            {feedback.strengths && feedback.strengths.length > 0 && (
                                                <div style={{ marginBottom: '16px' }}>
                                                    <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#22c55e', marginBottom: '8px' }}>
                                                        Strengths
                                                    </div>
                                                    <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '0.85rem', color: 'var(--muted-text)' }}>
                                                        {feedback.strengths.map((strength, idx) => (
                                                            <li key={idx} style={{ marginBottom: '4px' }}>{strength}</li>
                                                        ))}
                                                    </ul>
                                                </div>
                                            )}
                                            
                                            {feedback.weaknesses && feedback.weaknesses.length > 0 && (
                                                <div style={{ marginBottom: '16px' }}>
                                                    <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#f59e0b', marginBottom: '8px' }}>
                                                        Areas for Improvement
                                                    </div>
                                                    <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '0.85rem', color: 'var(--muted-text)' }}>
                                                        {feedback.weaknesses.map((weakness, idx) => (
                                                            <li key={idx} style={{ marginBottom: '4px' }}>{weakness}</li>
                                                        ))}
                                                    </ul>
                                                </div>
                                            )}
                                            
                                            {feedback.recommendations && feedback.recommendations.length > 0 && (
                                                <div>
                                                    <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#a78bfa', marginBottom: '8px' }}>
                                                        Recommendations
                    </div>
                                                    <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '0.85rem', color: 'var(--muted-text)' }}>
                                                        {feedback.recommendations.map((rec, idx) => (
                                                            <li key={idx} style={{ marginBottom: '4px' }}>{rec}</li>
                        ))}
                                                    </ul>
                    </div>
                    )}
                                        </div>
                                    </div>
                                </div>
                            </div>
                        );
                    })}
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
                        const isCompleted = data?.is_completed || false;
                        const score = isCompleted ? 100 : (data?.score || 0);
                        const color = isCompleted ? '#22c55e' : (score >= 70 ? '#22c55e' : score >= 40 ? '#f59e0b' : '#ef4444');
                        const isExpanded = expandedAgents[agentId];
                        const agentLabels = {
                            'agent1': 'Agent 1 - GPT4',
                            'agent2': 'Agent 2 - GPT 5',
                            'agent3': 'Agent 3 - GPT 4.1'
                        };
                        
                        return (
                            <div 
                                className={`agent-performance-item ${data ? 'clickable' : ''}`} 
                                key={agentId}
                                onClick={() => data && toggleAgent(agentId)}
                                style={{ cursor: data ? 'pointer' : 'default' }}
                            >
                                <div className="perf-header">
                                    <span className="perf-name">{agentLabels[agentId] || agentId}</span>
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
                                                isCompleted={isCompleted}
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

      {isGraphExpanded && progressGraph?.image_data_url && (
        <div 
          className="graph-expanded-overlay"
          onClick={() => setIsGraphExpanded(false)}
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.9)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            cursor: 'pointer',
            animation: 'fadeIn 0.3s ease-out'
          }}
        >
          <img 
            src={progressGraph.image_data_url} 
            alt="Agent Progress Graph - Expanded"
            onClick={(e) => e.stopPropagation()}
            style={{
              maxWidth: '90vw',
              maxHeight: '90vh',
              objectFit: 'contain',
              borderRadius: '8px',
              boxShadow: '0 20px 60px rgba(0, 0, 0, 0.5)',
              animation: 'expandImage 0.3s ease-out',
              cursor: 'default'
            }}
          />
        </div>
      )}
    </div>
  );
};

export default EvaluatorView;