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

const normalizePercent = (value) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return 0;
  }
  return Math.max(0, Math.min(100, Number(value)));
};

// Simple circular progress component
const CircularProgress = ({ percentage }) => {
  const radius = 16;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (percentage / 100) * circumference;

  return (
    <div className="circular-progress">
      <svg width="40" height="40" viewBox="0 0 40 40">
        <circle
          className="circular-progress__bg"
          cx="20"
          cy="20"
          r={radius}
        />
        <circle
          className="circular-progress__fill"
          cx="20"
          cy="20"
          r={radius}
          style={{ strokeDasharray: circumference, strokeDashoffset }}
        />
      </svg>
      <span className="circular-progress__text">{Math.round(percentage)}%</span>
    </div>
  );
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
      const { agent_id: agentId, vnc_url: vncUrl, latest_progress: latestProgress } = agent;
      const progressPercent = normalizePercent(latestProgress?.progress_percent);

      return (
        <article className="agent-card agent-card--clean" key={agentId}>
          <div className="agent-card__stream-wrapper">
            {/* Mini VNC Stream */}
            <VNCStreamMini 
              agentId={agentId}
              vncUrl={vncUrl}
            />
            
            {/* Overlay Progress */}
            <div className="agent-card__overlay">
              <CircularProgress percentage={progressPercent} />
            </div>

            {/* Agent Name Overlay */}
            <div className="agent-card__name-overlay">
              {agentId === 'agent1' ? 'GPT-5' : agentId === 'agent2' ? 'Sonnet 4.5' : agentId === 'agent3' ? 'GPT-4o' : (agentId || 'Unknown Agent')}
            </div>
          </div>
        </article>
      );
    });
  }, [agents]);

  return (
    <section className="live-feed">
      {error && (
        <div className="live-feed__error">{error}</div>
      )}

      {isLoading ? (
        <div className="live-feed__loading">Loading live feed…</div>
      ) : (
        <div className="agent-grid agent-grid--large">
          {agentCards || (
            <div className="agent-grid__empty">No agent data available yet.</div>
          )}
        </div>
      )}
    </section>
  );
};

export default AgentLiveFeed;
