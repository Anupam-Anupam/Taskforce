import React, { useState, useEffect } from 'react';
import { API_BASE, REFRESH_INTERVALS } from '../config';
import { buildAgentMessage, formatTime } from '../utils/chatUtils';
import liveIcon from '../images/live.png';
import evaluatorIcon from '../images/evaluator.png';

const Sidebar = ({ activeTab, setActiveTab }) => {
  const [latestMessages, setLatestMessages] = useState([]);

  useEffect(() => {
    let intervalId;
    
    const fetchLatestMessages = async () => {
      try {
        const response = await fetch(`${API_BASE}/chat/agent-responses?limit=5`); // Increased limit for larger preview
        if (!response.ok) return;
        
        const data = await response.json();
        const messages = (Array.isArray(data.messages) ? data.messages : [])
          .map(buildAgentMessage)
          .filter(Boolean);
          
        setLatestMessages(messages);
      } catch (error) {
        // Silent fail for sidebar preview
      }
    };

    fetchLatestMessages();
    intervalId = setInterval(fetchLatestMessages, REFRESH_INTERVALS.chat);

    return () => {
      if (intervalId) clearInterval(intervalId);
    };
  }, []);

  return (
    <aside className="app-sidebar">
      <div className="app-sidebar__header">
        <div className="app-logo">
          <span className="app-logo__orb" />
          <span className="app-logo__text">
            <span className="app-logo__label">Agent Task Force</span>
            <span className="app-logo__sub">Multi-agent control room</span>
          </span>
        </div>
      </div>

      <nav className="app-sidebar__nav">
        <button
          className={`sidebar-tab ${activeTab === 'agents' ? 'sidebar-tab--active' : ''}`}
          onClick={() => setActiveTab('agents')}
        >
          <span className="sidebar-tab__icon">
            <img src={liveIcon} alt="Live Agents" style={{ width: '3.0rem', height: '3.0rem', objectFit: 'overflow' }} />
          </span>
          <span className="sidebar-tab__label">Live Agents</span>
        </button>
        <button
          className={`sidebar-tab ${activeTab === 'evaluator' ? 'sidebar-tab--active' : ''}`}
          onClick={() => setActiveTab('evaluator')}
        >
          <span className="sidebar-tab__icon">
            <img src={evaluatorIcon} alt="Evaluator" style={{ width: '2.7rem', height: '2.7rem', objectFit: 'overflow' }} />
          </span>
          <span className="sidebar-tab__label">Evaluator</span>
        </button>

        <div 
          className={`sidebar-chat-preview ${activeTab === 'chat' ? 'sidebar-chat-preview--active' : ''}`}
          onClick={() => setActiveTab('chat')}
        >
          <div className="sidebar-chat-preview__header">
            <span className="sidebar-tab__icon">💬</span>
            <span className="sidebar-tab__label">Chat</span>
          </div>
          
          <div className="sidebar-chat-preview__messages">
            {latestMessages.length > 0 ? (
              latestMessages.map((msg) => (
                <div key={msg.id} className="sidebar-preview-msg">
                  <div className="sidebar-preview-msg__top">
                    <span className="sidebar-preview-msg__name">
                      {msg.sender === 'agent' ? msg.agentId : msg.sender}
                    </span>
                  </div>
                  <div className="sidebar-preview-msg__text">
                    {msg.text ? (msg.text.length > 100 ? msg.text.substring(0, 100) + '...' : msg.text) : '...'}
                  </div>
                </div>
              ))
            ) : (
              <div className="sidebar-preview-msg__empty">No messages yet</div>
            )}
          </div>
        </div>
      </nav>

      <div className="app-sidebar__footer">
        <div className="status-indicator">
          <span className="dot" />
          Live swarm
        </div>
      </div>
    </aside>
  );
};

export default Sidebar;

