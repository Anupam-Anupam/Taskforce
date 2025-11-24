import { useState } from 'react';
import Sidebar from './components/Sidebar';
import ChatTerminal from './components/ChatTerminal';
import AgentLiveFeed from './components/AgentLiveFeed';
import EvaluatorView from './components/EvaluatorView';
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

      <div className="app-layout">
        <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} />
        
        <main className="app-content">
          <section className="chat-view" style={{ display: activeTab === 'chat' ? 'flex' : 'none' }}>
            <ChatTerminal />
          </section>
          
          {activeTab === 'agents' && (
            <section>
              <AgentLiveFeed />
            </section>
          )}
          
          {activeTab === 'evaluator' && (
            <section>
              <EvaluatorView />
            </section>
          )}
        </main>
      </div>
    </div>
  );
}

export default App;
