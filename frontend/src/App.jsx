import { useState } from 'react';
import AgentLiveFeed from './components/AgentLiveFeed';
import EvaluatorView from './components/EvaluatorView';
import ChatPopup from './components/ChatPopup';
import './App.css';

function App() {
  const [activeTab, setActiveTab] = useState('agents');

  return (
    <div className="app">
      <div className="background-gradient" aria-hidden="true">
        <div className="gradient-1" />
        <div className="gradient-2" />
        <div className="gradient-3" />
      </div>

      <div className="app-shell">
        <header className="app-header">
          <div className="app-header__left">
            <div className="app-logo">
              <span className="app-logo__orb" />
              <span className="app-logo__text">
                <span className="app-logo__label">AI Village</span>
                <span className="app-logo__sub">Multi-agent control room</span>
              </span>
            </div>
          </div>

          <div className="app-header__right">
            <div className="app-header__meta">
              <span className="app-header__pill app-header__pill--live">
                <span className="dot" />
                Live swarm
              </span>
              <span className="app-header__pill app-header__pill--subtle">
                Designed for human + agent collaboration
              </span>
            </div>
          </div>
        </header>

        {/* Tab Navigation */}
        <nav className="app-tabs">
          <button
            className={`app-tab ${activeTab === 'agents' ? 'app-tab--active' : ''}`}
            onClick={() => setActiveTab('agents')}
          >
            <span className="app-tab__icon">🤖</span>
            <span className="app-tab__label">Agents</span>
          </button>
          <button
            className={`app-tab ${activeTab === 'evaluator' ? 'app-tab--active' : ''}`}
            onClick={() => setActiveTab('evaluator')}
          >
            <span className="app-tab__icon">📊</span>
            <span className="app-tab__label">Evaluator</span>
          </button>
        </nav>

        <main className="app-main">
          <section className="app-main__primary">
            {activeTab === 'agents' && <AgentLiveFeed />}
            {activeTab === 'evaluator' && <EvaluatorView />}
          </section>
        </main>
      </div>

      <ChatPopup />
    </div>
  );
}

export default App;
