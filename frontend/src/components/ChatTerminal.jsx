import { useState, useRef, useEffect, useCallback } from 'react';
import { API_BASE, REFRESH_INTERVALS } from '../config';
import { ensureDate, normalizePercent, formatPercentLabel, buildAgentMessage, formatTime } from '../utils/chatUtils';

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

  const upsertMessages = useCallback((incoming = [], { restampNew = false } = {}) => {
    if (!incoming.length) {
      return;
    }

    setMessages((prev) => {
      const map = new Map(prev.map((msg) => [msg.id, msg]));
      incoming.forEach((msg) => {
        if (!msg || msg.id === undefined || msg.id === null) {
          return;
        }
        
        let timestamp = ensureDate(msg.timestamp);
        
        // If restampNew is true, we want to use the current time for NEW messages
        // For existing messages, we prefer to keep the timestamp we already have
        if (restampNew) {
          const existing = map.get(msg.id);
          if (existing) {
            timestamp = existing.timestamp;
          } else {
            timestamp = new Date();
          }
        }

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
      
      // Check content-type before parsing JSON
      const contentType = response.headers.get('content-type');
      if (!contentType || !contentType.includes('application/json')) {
        throw new Error('Received non-JSON response from server');
      }

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
        upsertMessages(normalized, { restampNew: !isInitial });
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
      // Use the chat API which automatically creates tasks for user messages
      // and persists the message in chat history
      const response = await fetch(`${API_BASE}/chat/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          sender: 'user',
          message: taskText,
          metadata: {} 
        }),
      });

      // Check content-type before parsing JSON
      const contentType = response.headers.get('content-type');
      if (!contentType || !contentType.includes('application/json')) {
        throw new Error('Received non-JSON response from server');
      }

      const data = await response.json();

      setMessages((prev) => {
        // Remove thinking message
        const filtered = prev.filter((msg) => !msg.isThinking);
        // Update the optimistic message with the real ID from server if found
        return filtered.map(msg => {
          if (msg.id === userMessage.id) {
            return { ...msg, id: data.message_id || msg.id };
          }
          return msg;
        });
      });

      if (!response.ok) {
        throw new Error(data.detail || 'Failed to send message');
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
    <div className="chat-terminal" style={{ 
      height: '100%', 
      display: 'flex', 
      flexDirection: 'column',
      backgroundColor: 'transparent',
      position: 'relative',
      overflow: 'hidden'
    }}>
      {/* Chat content with higher z-index */}
      <div 
        ref={messagesContainerRef}
        onScroll={checkScrollPosition}
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '20px',
          display: 'flex',
          flexDirection: 'column',
          gap: '24px',
          backgroundColor: 'transparent',
          position: 'relative',
          alignItems: 'center',
          zIndex: 1
        }}
      >
        <div style={{ width: '100%', maxWidth: '800px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
          {historyLoading && (
            <div style={{ color: '#a3a3a3', fontSize: '0.95rem', textAlign: 'center', marginTop: '20px' }}>
              Loading conversation…
            </div>
          )}

          {!historyLoading && messages.length === 0 && !historyError && (
            <div style={{ color: '#a3a3a3', fontSize: '0.95rem', textAlign: 'center', marginTop: '40px' }}>
              <div style={{ fontSize: '2rem', marginBottom: '16px' }}>👋</div>
              <div style={{ fontWeight: 600, color: '#e5e5e5', marginBottom: '8px' }}>Welcome to AI Village</div>
              <div>Enter a task below to start the swarm.</div>
            </div>
          )}

          {historyError && (
            <div style={{
              color: '#f87171',
              backgroundColor: 'rgba(239, 68, 68, 0.1)',
              border: '1px solid rgba(239, 68, 68, 0.2)',
              borderRadius: '8px',
              padding: '12px 16px',
              textAlign: 'center'
            }}>
              {historyError}
            </div>
          )}

          {messages.map((message) => {
            // Updated color mapping for dark purple theme
            // Using darker backgrounds with purple accents
            const agentColors = {
              'agent1': { bg: 'rgba(6, 78, 59, 0.4)', text: '#34d399', name: 'Agent 1', emoji: '🤖', border: '#065f46' },
              'agent2': { bg: 'rgba(30, 64, 175, 0.4)', text: '#60a5fa', name: 'Agent 2', emoji: '🦾', border: '#1e40af' },
              'agent3': { bg: 'rgba(124, 58, 237, 0.3)', text: '#a78bfa', name: 'Agent 3', emoji: '🧠', border: '#6d28d9' },
              'system': { bg: 'rgba(38, 38, 38, 0.6)', text: '#a3a3a3', name: 'System', emoji: '⚙️', border: '#404040' },
              'user': { bg: 'rgba(38, 38, 38, 0.6)', text: '#a3a3a3', name: 'You', emoji: '👤', border: '#404040' }
            };

            const agentInfo = agentColors[message.agentId] || agentColors[message.sender] || agentColors['system'];
            
            return (
              <div
                key={message.id}
                style={{
                  display: 'flex',
                  gap: '16px',
                  alignItems: 'flex-start',
                  padding: '4px 0'
                }}
              >
                {/* Avatar */}
                <div style={{
                  width: '36px',
                  height: '36px',
                  borderRadius: '4px', 
                  backgroundColor: agentInfo.bg,
                  color: agentInfo.text,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '1.2rem',
                  flexShrink: 0,
                  boxShadow: '0 4px 12px rgba(0,0,0,0.2)',
                  border: `1px solid ${agentInfo.border}`,
                  backdropFilter: 'blur(8px)'
                }}>
                  {agentInfo.emoji}
                </div>

                {/* Message body */}
                <div style={{
                  flex: 1,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '6px',
                  padding: '16px',
                  backgroundColor: 'rgba(38, 38, 38, 0.55)',
                  borderRadius: '16px',
                  border: '1px solid rgba(255, 255, 255, 0.05)',
                  backdropFilter: 'blur(4px)'
                }}>
                  {/* Header */}
                  <div style={{
                    display: 'flex',
                    alignItems: 'baseline',
                    gap: '10px',
                    fontSize: '0.9rem'
                  }}>
                    <span style={{ 
                      fontWeight: 600,
                      color: '#e5e5e5'
                    }}>
                      {agentInfo.name}
                    </span>
                    {!message.isThinking && (
                      <span style={{ 
                        fontSize: '0.75rem', 
                        color: '#737373',
                      }}>
                        {formatTime(message.timestamp)}
                      </span>
                    )}
                  </div>

                  {/* Content */}
                  <div style={{
                    color: '#d4d4d4',
                    fontSize: '1rem',
                    lineHeight: '1.6',
                    wordBreak: 'break-word',
                  }}>
                    <div style={{ whiteSpace: 'pre-wrap' }}>
                      {message.text ? String(message.text) : ''}
                      {message.isThinking && (
                        <span style={{ display: 'inline-flex', gap: '4px', marginLeft: '4px' }}>
                          <span style={{ animation: 'blink 1.4s infinite' }}>.</span>
                          <span style={{ animation: 'blink 1.4s infinite 0.2s' }}>.</span>
                          <span style={{ animation: 'blink 1.4s infinite 0.4s' }}>.</span>
                        </span>
                      )}
                    </div>

                    {/* Progress badge */}
                    {!message.isThinking && formatPercentLabel(message.progressPercent) && (
                      <div style={{
                        marginTop: '12px',
                        display: 'inline-block'
                      }}>
                        <span style={{
                          padding: '4px 10px',
                          borderRadius: '12px',
                          backgroundColor: 'rgba(124, 58, 237, 0.15)',
                          border: '1px solid rgba(124, 58, 237, 0.3)',
                          color: '#a78bfa',
                          fontSize: '0.8rem',
                          fontWeight: '500'
                        }}>
                          Progress: {formatPercentLabel(message.progressPercent)}
                        </span>
                      </div>
                    )}

                    {/* Task metadata */}
                    {(message.taskId || message.taskTitle || message.taskStatus) && (
                      <div style={{
                        marginTop: '8px',
                        fontSize: '0.8rem',
                        color: '#737373',
                        display: 'flex',
                        flexWrap: 'wrap',
                        gap: '12px',
                      }}>
                        {message.taskId && <span>ID: {message.taskId}</span>}
                        {message.taskStatus && <span>Status: {message.taskStatus}</span>}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
          <div ref={messagesEndRef} />
        </div>
        
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

      <div style={{
        padding: '24px',
        width: '100%',
        display: 'flex',
        justifyContent: 'center',
        background: 'linear-gradient(to top, #0a0a0a 80%, transparent)',
        paddingBottom: '40px',
        zIndex: 1,
        position: 'relative'
      }}>
        <form onSubmit={handleSubmit} style={{
          maxWidth: '800px',
          width: '100%',
          position: 'relative'
        }}>
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="Send a message to the agents..."
            disabled={isLoading}
            style={{
              width: '100%',
              padding: '16px 50px 16px 20px',
              backgroundColor: 'rgba(26, 26, 26, 0.8)',
              border: '1px solid rgba(255, 255, 255, 0.1)',
              borderRadius: '16px',
              color: '#e5e5e5',
              fontSize: '1rem',
              outline: 'none',
              boxShadow: '0 4px 20px rgba(0, 0, 0, 0.4)',
              backdropFilter: 'blur(12px)'
            }}
          />
          <button
            type="submit"
            disabled={!inputValue.trim() || isLoading}
            style={{
              position: 'absolute',
              right: '12px',
              top: '50%',
              transform: 'translateY(-50%)',
              background: inputValue.trim() ? '#7c3aed' : 'transparent',
              color: inputValue.trim() ? '#ffffff' : '#737373',
              border: 'none',
              borderRadius: '8px',
              padding: '8px',
              cursor: inputValue.trim() ? 'pointer' : 'default',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'all 0.2s',
              boxShadow: inputValue.trim() ? '0 0 15px rgba(124, 58, 237, 0.5)' : 'none'
            }}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="22" y1="2" x2="11" y2="13"></line>
              <path d="M22 2L15 22 11 13 2 9 22 2z"></path>
            </svg>
          </button>
        </form>
      </div>
    </div>
  );
};

export default ChatTerminal;
