import { useEffect, useMemo, useState } from 'react';
import { API_BASE, REFRESH_INTERVALS } from '../config';
import VNCStreamMini from './VNCStreamMini';
import '../App.css';

const formatTime = (timestamp) => {
  if (!timestamp) return '—';
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return timestamp;
  }
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};

const formatPercent = (value) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return null;
  }
  const parsed = Math.max(0, Math.min(100, Number(value)));
  return `${parsed.toFixed(0)}%`;
};

const AgentLiveFeed = () => {
  const [agents, setAgents] = useState([]);
  const [generatedAt, setGeneratedAt] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let ignore = false;
    let intervalId;

    const fetchLiveData = async () => {
      try {
        const response = await fetch(`${API_BASE}/agents/live?limit_per_agent=3`);
        const data = await response.json();

        if (!response.ok) {
          throw new Error(data.detail || 'Failed to load agent feed');
        }

        if (!ignore) {
          setAgents(Array.isArray(data.agents) ? data.agents : []);
          setGeneratedAt(data.generated_at || null);
          setError(null);
          setIsLoading(false);
        }
      } catch (err) {
        if (!ignore) {
          setError(err.message || 'Unable to load agent feed');
          setIsLoading(false);
        }
      }
    };

    fetchLiveData();
    intervalId = setInterval(fetchLiveData, REFRESH_INTERVALS.liveFeed);

    return () => {
      ignore = true;
      if (intervalId) {
        clearInterval(intervalId);
      }
    };
  }, []);

  const agentCards = useMemo(() => {
    if (!agents.length) {
      return null;
    }

    return agents.map((agent) => {
      const { agent_id: agentId, vnc_url: vncUrl, latest_progress: latestProgress, progress_updates: progressUpdates = [] } = agent;
      const percentLabel = latestProgress ? formatPercent(latestProgress.progress_percent) : null;

      return (
        <article className="agent-card" key={agentId}>
          <div className="agent-card__header">
            <div>
              <h2 className="agent-card__title">{agentId || 'Unknown Agent'}</h2>
              <p className="agent-card__subtitle">
                {latestProgress?.message || 'Waiting for progress update'}
              </p>
            </div>
            <div className={`agent-card__pill ${percentLabel ? 'agent-card__pill--active' : ''}`}>
              {percentLabel || '—'}
            </div>
          </div>

          {/* Mini VNC Stream - Just the live feed, nothing else */}
          <VNCStreamMini 
            agentId={agentId}
            vncUrl={vncUrl}
          />

          <div className="agent-card__meta">
            <span>Last update: {formatTime(latestProgress?.timestamp)}</span>
          </div>

          {progressUpdates.length > 0 && (
            <ul className="agent-card__updates">
              {progressUpdates.slice(0, 3).map((update, index) => (
                <li key={`${agentId}-${index}-${update.timestamp || index}`}
                    className="agent-card__update">
                  <div className="agent-card__update-time">{formatTime(update.timestamp)}</div>
                  <div className="agent-card__update-body">
                    {formatPercent(update.progress_percent) && (
                      <span className="agent-card__update-progress">
                        {formatPercent(update.progress_percent)}
                      </span>
                    )}
                    <span>{update.message || 'Progress update received'}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </article>
      );
    });
  }, [agents]);

  return (
    <section className="live-feed">
      <header className="live-feed__header">
        <div>
          <h1>AI Village Control Center</h1>
          <p>Monitor agent activity, live VNC streams, and progress in real time.</p>
        </div>
        <div className="live-feed__meta">
          <span>Last refreshed: {generatedAt ? formatTime(generatedAt) : '—'}</span>
        </div>
      </header>

      {error && (
        <div className="live-feed__error">{error}</div>
      )}

      {isLoading ? (
        <div className="live-feed__loading">Loading live feed…</div>
      ) : (
        <div className="agent-grid">
          {agentCards || (
            <div className="agent-grid__empty">No agent data available yet.</div>
          )}
        </div>
      )}
    </section>
  );
};

export default AgentLiveFeed;
