import { useState, useRef, useEffect, useCallback } from 'react';
import { API_BASE, REFRESH_INTERVALS } from '../config';

// Utility: ensure we have a Date object
const ensureDate = (val) => {
  if (val instanceof Date) return val;
  if (typeof val === 'string' || typeof val === 'number') {
    const d = new Date(val);
    return isNaN(d.getTime()) ? new Date() : d;
  }
  return new Date();
};

// Normalize progress percent to 0-100
const normalizePercent = (val) => {
  if (val == null || val === '') return null;
  const num = parseFloat(val);
  if (isNaN(num)) return null;
  return Math.max(0, Math.min(100, num));
};

const formatPercentLabel = (val) => {
  const p = normalizePercent(val);
  return p !== null ? `${Math.round(p)}%` : null;
};

// Build a chat message from agent response data
const buildAgentMessage = (item) => {
  if (!item || !item.id) return null;
  return {
    id: item.id,
    agentId: item.agent_id || 'unknown',
    sender: 'agent',
    text: item.message || '',
    timestamp: ensureDate(item.timestamp),
    progressPercent: item.progress_percent,
    taskId: item.task?.id || item.task_id,
    taskTitle: item.task?.title,
    taskStatus: item.task?.status,
  };
};

const formatTime = (date) => {
  if (!date) {
    return '—';
  }
  const safeDate = ensureDate(date);
  return safeDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};

const getSenderLabel = (message) => {
  if (message.sender === 'user') {
    return 'You';
  }
  if (message.sender === 'system') {
    return 'System';
  }
  return message.agentId || 'Agent';
};

const ChatTerminal = () => {
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState(null);
  const [showScrollButton, setShowScrollButton] = useState(false);
  const [hasNewMessages, setHasNewMessages] = useState(false);
  const messagesEndRef = useRef(null);
  const messagesContainerRef = useRef(null);
  const abortRef = useRef(false);
  const prevMessageCountRef = useRef(0);

  const upsertMessages = useCallback((incoming = []) => {
    if (!incoming.length) {
      return;
    }

    setMessages((prev) => {
      const map = new Map(prev.map((msg) => [msg.id, msg]));
      incoming.forEach((msg) => {
        if (!msg || msg.id === undefined || msg.id === null) {
          return;
        }
        const timestamp = ensureDate(msg.timestamp);
        map.set(msg.id, { ...msg, timestamp });
      });

      // Sort by timestamp and keep only the last 50 messages
      const sortedMessages = Array.from(map.values()).sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime());
      return sortedMessages.slice(-50);
    });
  }, []);

  const lastFetchTimeRef = useRef(null);

  const fetchAgentResponses = useCallback(async (isInitial = false) => {
    try {
      // Build URL with optional 'since' parameter for incremental updates
      let url = `${API_BASE}/chat/agent-responses?limit=50`;
      if (!isInitial && lastFetchTimeRef.current) {
        url += `&since=${encodeURIComponent(lastFetchTimeRef.current)}`;
      }
      
      const response = await fetch(url);
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || 'Failed to load agent responses');
      }

      if (abortRef.current) {
        return;
      }

      const normalized = (Array.isArray(data.messages) ? data.messages : [])
        .map(buildAgentMessage)
        .filter(Boolean);

      if (normalized.length) {
        upsertMessages(normalized);
        // Update last fetch time to the most recent message timestamp
        const latestTimestamp = normalized[0]?.timestamp;
        if (latestTimestamp) {
          lastFetchTimeRef.current = latestTimestamp.toISOString();
        }
      }
      setHistoryError(null);
    } catch (error) {
        if (abortRef.current) {
          return;
        }
        console.error('Error loading agent responses:', error);
        setHistoryError(error?.message ? String(error.message) : 'Unable to load agent responses');
    } finally {
      if (!abortRef.current) {
        setHistoryLoading(false);
      }
    }
  }, [upsertMessages]);

  useEffect(() => {
    abortRef.current = false;

    // Initial fetch gets all messages
    fetchAgentResponses(true);
    
    // Subsequent fetches only get new messages
    const intervalId = setInterval(() => fetchAgentResponses(false), REFRESH_INTERVALS.chat);

    return () => {
      abortRef.current = true;
      clearInterval(intervalId);
    };
  }, [fetchAgentResponses]);

  // Check if user is scrolled to bottom
  const checkScrollPosition = useCallback(() => {
    if (!messagesContainerRef.current) return;
    
    const { scrollTop, scrollHeight, clientHeight } = messagesContainerRef.current;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 50; // 50px threshold
    
    setShowScrollButton(!isAtBottom);
    
    // Clear new message indicator if at bottom
    if (isAtBottom) {
      setHasNewMessages(false);
    }
  }, []);

  // Scroll to bottom function
  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    setHasNewMessages(false);
  }, []);

  // Effect to update prevMessageCountRef when messages change
  useEffect(() => {
    prevMessageCountRef.current = messages.length;
  }, [messages]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!inputValue.trim() || isLoading) return;

    const taskText = inputValue.trim();
    const taskTimestamp = new Date();

    // Add user message to chat like a group chat
    const userMessage = {
      id: `user-${Date.now()}`,
      sender: 'user',
      text: taskText,
      timestamp: new Date(),
    };

    upsertMessages([userMessage]);
    setInputValue('');
    setIsLoading(true);

    const thinkingMessage = {
      id: `thinking-${Date.now()}`,
      sender: 'system',
      text: 'Sending task to agents...',
      timestamp: new Date(),
      isThinking: true,
    };

    upsertMessages([thinkingMessage]);

    try {
      const response = await fetch(`${API_BASE}/task`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: taskText, timestamp: taskTimestamp.toISOString() }),
      });
      const data = await response.json();

      setMessages((prev) => prev.filter((msg) => !msg.isThinking));

      if (response.ok) {
        // Don't add task creation message - only show final agent responses
        // The agent response will appear automatically when it completes
      } else {
        throw new Error(data.detail || 'Failed to create task');
      }
    } catch (error) {
      setMessages((prev) => prev.filter((msg) => !msg.isThinking));

      const errorMessage = {
        id: `error-${Date.now()}`,
        sender: 'system',
        text: `Error: ${error?.message ? String(error.message) : String(error)}`,
        timestamp: new Date(),
        isError: true,
      };
      upsertMessages([errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="chat-terminal">
      <header className="chat-terminal__header">
        <div>
          <div className="chat-terminal__title">Agent Playground</div>
          <div className="chat-terminal__subtitle">Share a task and watch the agents report back.</div>
        </div>
      </header>

      <div 
        ref={messagesContainerRef}
        onScroll={checkScrollPosition}
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '20px',
          display: 'flex',
          flexDirection: 'column',
          gap: '15px',
          backgroundColor: '#151c19',
          position: 'relative'
        }}
      >
        {historyLoading && (
          <div style={{ color: '#a9b0c5', fontSize: '0.95rem' }}>
            Loading conversation…
          </div>
        )}

        {!historyLoading && messages.length === 0 && !historyError && (
          <div style={{ color: '#a9b0c5', fontSize: '0.95rem' }}>
            Waiting for agent responses…
          </div>
        )}

        {historyError && (
          <div style={{
            color: '#ff6b6b',
            backgroundColor: 'rgba(255, 107, 107, 0.1)',
            border: '1px solid rgba(255, 107, 107, 0.3)',
            borderRadius: '8px',
            padding: '12px 16px'
          }}>
            {historyError}
          </div>
        )}

        {messages.map((message) => {
          // Agent color mapping for group chat style
          const agentColors = {
            'agent1': { bg: '#88d6a4', name: 'Agent 1', emoji: '🤖' },
            'agent2': { bg: '#7ab8ff', name: 'Agent 2', emoji: '🦾' },
            'agent3': { bg: '#f4bf67', name: 'Agent 3', emoji: '🧠' },
            'system': { bg: '#a9b0c5', name: 'System', emoji: '⚙️' },
            'user': { bg: '#e89ac7', name: 'You', emoji: '👤' }
          };

          const agentInfo = agentColors[message.agentId] || agentColors[message.sender] || agentColors['system'];

          return (
            <div
              key={message.id}
              style={{
                display: 'flex',
                gap: '12px',
                alignItems: 'flex-start'
              }}
            >
              {/* Avatar */}
              <div style={{
                width: '40px',
                height: '40px',
                borderRadius: '50%',
                backgroundColor: agentInfo.bg,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '1.3rem',
                flexShrink: 0,
                boxShadow: '0 2px 8px rgba(0,0,0,0.2)'
              }}>
                {agentInfo.emoji}
              </div>

              {/* Message bubble */}
              <div style={{
                flex: 1,
                display: 'flex',
                flexDirection: 'column',
                gap: '6px'
              }}>
                {/* Header: name and time */}
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  fontSize: '0.85rem'
                }}>
                  <span style={{ 
                    fontWeight: 'bold',
                    color: agentInfo.bg
                  }}>
                    {agentInfo.name}
                  </span>
                  {!message.isThinking && (
                    <span style={{ 
                      fontSize: '0.75rem', 
                      color: '#868ea4',
                      opacity: 0.8
                    }}>
                      {formatTime(message.timestamp)}
                    </span>
                  )}
                </div>

                {/* Message content bubble */}
                <div style={{
                  backgroundColor: '#2a3530',
                  padding: '12px 16px',
                  borderRadius: '12px',
                  borderTopLeftRadius: '4px',
                  color: '#e0e8e5',
                  fontSize: '0.95rem',
                  lineHeight: '1.5',
                  wordBreak: 'break-word',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.15)',
                  position: 'relative'
                }}>
                  <div style={{
                    display: 'flex',
                    flexWrap: 'wrap',
                    gap: '8px',
                    alignItems: 'center'
                  }}>
                    <span>{message.text ? String(message.text) : ''}</span>
                    {message.isThinking && (
                      <span style={{ display: 'inline-flex', gap: '4px' }}>
                        <span style={{ animation: 'blink 1.4s infinite' }}>.</span>
                        <span style={{ animation: 'blink 1.4s infinite 0.2s' }}>.</span>
                        <span style={{ animation: 'blink 1.4s infinite 0.4s' }}>.</span>
                      </span>
                    )}
                  </div>

                  {/* Progress badge */}
                  {!message.isThinking && formatPercentLabel(message.progressPercent) && (
                    <div style={{
                      marginTop: '8px',
                      display: 'inline-block'
                    }}>
                      <span style={{
                        padding: '4px 10px',
                        borderRadius: '12px',
                        backgroundColor: agentInfo.bg,
                        color: '#1a2420',
                        fontSize: '0.8rem',
                        fontWeight: 'bold',
                        boxShadow: '0 1px 3px rgba(0,0,0,0.2)'
                      }}>
                        {formatPercentLabel(message.progressPercent)}
                      </span>
                    </div>
                  )}

                  {/* Task metadata */}
                  {(message.taskId || message.taskTitle || message.taskStatus) && (
                    <div style={{
                      marginTop: '8px',
                      fontSize: '0.75rem',
                      color: '#a9b0c5',
                      display: 'flex',
                      flexWrap: 'wrap',
                      gap: '8px',
                      opacity: 0.8
                    }}>
                      {message.taskId && <span>#{message.taskId}</span>}
                      {message.taskTitle && <span>• {message.taskTitle}</span>}
                      {message.taskStatus && <span>• {message.taskStatus}</span>}
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}
        <div ref={messagesEndRef} />
        {showScrollButton && (
          <button 
            className={`scroll-to-bottom-button ${showScrollButton ? 'show' : ''}`}
            onClick={scrollToBottom}
            aria-label="Scroll to bottom"
          >
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 5v14"></path>
              <path d="m19 12-7 7-7-7"></path>
            </svg>
            {hasNewMessages && <span className="scroll-to-bottom-button__dot" />}
          </button>
        )}
      </div>

      <form onSubmit={handleSubmit} style={{
        padding: '15px',
        backgroundColor: '#2e3a36',
        borderTop: '1px solid rgba(255, 255, 255, 0.06)',
        display: 'flex',
        gap: '10px'
      }}>
        <input
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          placeholder="Enter a joyful mission for the agents…"
          disabled={isLoading}
          style={{
            flex: 1,
            padding: '12px 15px',
            backgroundColor: '#3a4a45',
            border: '1px solid rgba(255, 255, 255, 0.06)',
            borderRadius: '999px',
            color: '#e0e8e5',
            fontSize: '0.95rem',
            outline: 'none'
          }}
        />
        <button
          type="submit"
          disabled={!inputValue.trim() || isLoading}
          className="chat-terminal__send"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="22" y1="2" x2="11" y2="13"></line>
            <path d="M22 2L15 22 11 13 2 9 22 2z"></path>
          </svg>
          Send
        </button>
      </form>
    </div>
  );
};

export default ChatTerminal;
