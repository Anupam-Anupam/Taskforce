import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { API_BASE, REFRESH_INTERVALS } from '../config';
import { ensureDate, normalizePercent, formatPercentLabel, buildAgentMessage, formatTime } from '../utils/chatUtils';
import collaborateIcon from '../images/928470d7-332a-416c-82cf-871acd43342a.png';
import Aurora from './Aurora';

const AVAILABLE_AGENTS = ['agent1', 'agent2', 'agent3'];

const detectTaggedAgents = (text = '') => {
  if (!text) return [];
  const normalized = text.toLowerCase();
  if (normalized.includes('@all')) {
    return AVAILABLE_AGENTS;
  }
  const detected = AVAILABLE_AGENTS.filter((agentId) =>
    normalized.includes(`@${agentId.toLowerCase()}`)
  );
  return detected;
};

const ChatTerminal = () => {
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [caretPosition, setCaretPosition] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState(null);
  const [showScrollButton, setShowScrollButton] = useState(false);
  const [hasNewMessages, setHasNewMessages] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [passwordInput, setPasswordInput] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const messagesEndRef = useRef(null);
  const messagesContainerRef = useRef(null);
  const inputRef = useRef(null);
  const composerRef = useRef(null);
  const abortRef = useRef(false);
  const prevMessageCountRef = useRef(0);
  const [agentsStatus, setAgentsStatus] = useState({});
  const [mentionQuery, setMentionQuery] = useState('');
  const [isMentionMenuVisible, setMentionMenuVisible] = useState(false);
  const [mentionCoords, setMentionCoords] = useState({ left: 0, top: 0 });
  const [isCollaborateMode, setIsCollaborateMode] = useState(false);
  const [isHoveringModeButton, setIsHoveringModeButton] = useState(false);
  const [sessionStartTime, setSessionStartTime] = useState(null);
  const [firstTaskId, setFirstTaskId] = useState(null);

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

      // Sort by timestamp to maintain chronological order (like a chat)
      // Messages with the same task ID will be grouped together, but maintain time order
      const sortedMessages = Array.from(map.values()).sort((a, b) => {
        const timeA = a.timestamp instanceof Date ? a.timestamp.getTime() : new Date(a.timestamp).getTime();
        const timeB = b.timestamp instanceof Date ? b.timestamp.getTime() : new Date(b.timestamp).getTime();
        return timeA - timeB;
      });
      return sortedMessages.slice(-50);
    });
  }, []);

  const fetchAgentsStatus = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/agents/status`);
      const data = await response.json();
      if (response.ok && data) {
        setAgentsStatus(data);
      }
    } catch (err) {
      // ignore, UI just won't show status
    }
  }, []);

  useEffect(() => {
    fetchAgentsStatus();
    const intervalId = setInterval(fetchAgentsStatus, REFRESH_INTERVALS.liveFeed);
    return () => clearInterval(intervalId);
  }, [fetchAgentsStatus]);

  const updateMentionState = useCallback((value, cursorPos) => {
    if (cursorPos == null) {
      cursorPos = value.length;
    }
    const textBeforeCursor = value.slice(0, cursorPos);
    const mentionMatch = textBeforeCursor.match(/@([a-z0-9_-]*)$/i);
    if (mentionMatch) {
      setMentionQuery(mentionMatch[1].toLowerCase());
      setMentionMenuVisible(true);
      if (inputRef.current && composerRef.current) {
        const inputRect = inputRef.current.getBoundingClientRect();
        const composerRect = composerRef.current.getBoundingClientRect();
        setMentionCoords({
          left: Math.max(0, inputRect.left - composerRect.left),
          top: inputRect.top - composerRect.top,
        });
      } else {
        setMentionCoords({ left: 0, top: 0 });
      }
    } else {
      setMentionMenuVisible(false);
      setMentionQuery('');
    }
  }, []);

  const handleInputChange = useCallback((e) => {
    const { value, selectionStart } = e.target;
    setInputValue(value);
    setCaretPosition(selectionStart || value.length);
    updateMentionState(value, selectionStart || value.length);
  }, [updateMentionState]);

  const handleInputSelect = useCallback((e) => {
    const { selectionStart } = e.target;
    setCaretPosition(selectionStart || 0);
    updateMentionState(e.target.value, selectionStart || 0);
  }, [updateMentionState]);

  const mentionOptions = useMemo(() => {
    const query = mentionQuery.trim();
    return AVAILABLE_AGENTS.filter((agentId) =>
      !query || agentId.toLowerCase().includes(query)
    );
  }, [mentionQuery]);

  const resolvedStatus = useCallback((agentId) => {
    const raw = agentsStatus[agentId];
    if (!raw) return 'online'; // default optimistic
    return raw === 'stopped' ? 'offline' : 'online';
  }, [agentsStatus]);

  const insertMention = useCallback((agentId) => {
    if (!inputRef.current) return;
    const currentValue = inputRef.current.value;
    const cursor = caretPosition;
    const textBeforeCursor = currentValue.slice(0, cursor);
    const mentionMatch = textBeforeCursor.match(/@([a-z0-9_-]*)$/i);
    let startIndex = cursor;
    if (mentionMatch) {
      startIndex = cursor - mentionMatch[1].length - 1;
    }
    const before = currentValue.slice(0, startIndex);
    const after = currentValue.slice(cursor);
    const newValue = `${before}@${agentId} ${after}`.replace(/\s{2,}/g, ' ');
    setInputValue(newValue);
    setMentionMenuVisible(false);
    const newCursor = before.length + agentId.length + 2;
    requestAnimationFrame(() => {
      inputRef.current?.focus();
      inputRef.current?.setSelectionRange(newCursor, newCursor);
      setCaretPosition(newCursor);
    });
  }, [caretPosition]);
  const handlePasswordSubmit = (e) => {
    e.preventDefault();
    if (passwordInput === 'jubilee') {
      setIsAuthenticated(true);
      setPasswordError('');
      setPasswordInput('');
    } else {
      setPasswordError('Incorrect password. Please try again.');
      setPasswordInput('');
    }
  };

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
        
        // Track first task ID from messages if session has started but firstTaskId not set
        if (sessionStartTime && !firstTaskId) {
          const taskIds = normalized
            .map(msg => parseInt(msg.taskId) || null)
            .filter(id => id !== null);
          if (taskIds.length > 0) {
            const minTaskId = Math.min(...taskIds);
            setFirstTaskId(minTaskId);
          }
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
    if (messagesContainerRef.current) {
      const container = messagesContainerRef.current;
      container.scrollTo({
        top: container.scrollHeight,
        behavior: 'smooth'
      });
    } else if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
    setHasNewMessages(false);
  }, []);

  // Effect to update prevMessageCountRef when messages change
  useEffect(() => {
    prevMessageCountRef.current = messages.length;
    
    // Auto-scroll to bottom when new messages are added (only if user is near bottom)
    if (messagesContainerRef.current && sessionStartTime) {
      const container = messagesContainerRef.current;
      const { scrollTop, scrollHeight, clientHeight } = container;
      const isNearBottom = scrollHeight - scrollTop - clientHeight < 100; // 100px threshold
      
      if (isNearBottom) {
        // Small delay to ensure DOM is updated
        requestAnimationFrame(() => {
          if (messagesContainerRef.current) {
            messagesContainerRef.current.scrollTo({
              top: messagesContainerRef.current.scrollHeight,
              behavior: 'smooth'
            });
          }
        });
      }
    }
  }, [messages, sessionStartTime]);

  // Auto-scroll to bottom when chat opens (history finishes loading) or when authenticated
  useEffect(() => {
    if (!historyLoading && sessionStartTime) {
      const sessionMessages = messages.filter(msg => {
        const msgTime = msg.timestamp instanceof Date ? msg.timestamp : new Date(msg.timestamp);
        return msgTime >= sessionStartTime;
      });
      if (sessionMessages.length > 0) {
        // Small delay to ensure DOM is ready
        setTimeout(() => {
          scrollToBottom();
        }, 100);
      }
    }
  }, [historyLoading, isAuthenticated, messages.length, sessionStartTime, scrollToBottom]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!isAuthenticated) {
      return; // Don't allow sending messages if not authenticated
    }
    if (!inputValue.trim() || isLoading) return;

    // Set session start time on first message
    if (!sessionStartTime) {
      setSessionStartTime(new Date());
    }

    const taskText = inputValue.trim();
    const taskTimestamp = new Date();

    // Add user message to chat like a group chat
    // Note: taskId will be assigned when we get the response from the server
    const userMessage = {
      id: `user-${Date.now()}`,
      sender: 'user',
      text: taskText,
      timestamp: new Date(),
      taskId: null, // Will be set from API response
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
          metadata: {
            mode: isCollaborateMode ? 'collaborate' : 'solo'
          } 
        }),
      });

      // Check content-type before parsing JSON
      const contentType = response.headers.get('content-type');
      if (!contentType || !contentType.includes('application/json')) {
        throw new Error('Received non-JSON response from server');
      }

      const data = await response.json();

      // Track first task ID on first message
      if (!firstTaskId && data.task_id) {
        setFirstTaskId(data.task_id);
      }

      setMessages((prev) => {
        // Remove thinking message
        const filtered = prev.filter((msg) => !msg.isThinking);
        // Update the optimistic message with the real ID and task ID from server
        const updated = filtered.map(msg => {
          if (msg.id === userMessage.id) {
            // Always assign the task ID from the API response to the user message
            return { 
              ...msg, 
              id: data.message_id || msg.id, 
              taskId: data.task_id || null
            };
          }
          return msg;
        });
        
        // If no task_id in response yet, find the minimum task ID from all messages
        if (!firstTaskId) {
          const taskIds = updated
            .map(msg => parseInt(msg.taskId) || null)
            .filter(id => id !== null && id > 0);
          if (taskIds.length > 0) {
            const minTaskId = Math.min(...taskIds);
            setFirstTaskId(minTaskId);
          }
        }
        
        return updated;
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

  // Show password screen if not authenticated
  if (!isAuthenticated) {
    return (
      <div className="chat-terminal" style={{ 
        height: '100%', 
        display: 'flex', 
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: 'transparent',
        position: 'relative'
      }}>
        <div style={{
          backgroundColor: 'rgba(38, 38, 38, 0.95)',
          padding: '40px',
          borderRadius: '16px',
          border: '1px solid rgba(124, 58, 237, 0.3)',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.4)',
          maxWidth: '400px',
          width: '90%'
        }}>
          <h2 style={{
            color: '#e5e5e5',
            marginBottom: '10px',
            fontSize: '1.5rem',
            textAlign: 'center'
          }}>
            🔒 Authentication Required
          </h2>
          <p style={{
            color: '#a3a3a3',
            marginBottom: '24px',
            textAlign: 'center',
            fontSize: '0.9rem'
          }}>
            Enter password to access chat
          </p>
          <form onSubmit={handlePasswordSubmit}>
            <input
              type="password"
              value={passwordInput}
              onChange={(e) => setPasswordInput(e.target.value)}
              placeholder="Enter password..."
              autoFocus
              style={{
                width: '100%',
                padding: '12px 16px',
                backgroundColor: 'rgba(0, 0, 0, 0.3)',
                border: '1px solid rgba(255, 255, 255, 0.1)',
                borderRadius: '8px',
                color: '#e5e5e5',
                fontSize: '1rem',
                marginBottom: '16px',
                outline: 'none',
                transition: 'border-color 0.2s'
              }}
              onFocus={(e) => e.target.style.borderColor = 'rgba(124, 58, 237, 0.5)'}
              onBlur={(e) => e.target.style.borderColor = 'rgba(255, 255, 255, 0.1)'}
            />
            {passwordError && (
              <div style={{
                color: '#ef4444',
                fontSize: '0.85rem',
                marginBottom: '16px',
                textAlign: 'center'
              }}>
                {passwordError}
              </div>
            )}
            <button
              type="submit"
              style={{
                width: '100%',
                padding: '12px',
                backgroundColor: 'rgba(124, 58, 237, 0.8)',
                border: 'none',
                borderRadius: '8px',
                color: '#fff',
                fontSize: '1rem',
                fontWeight: 600,
                cursor: 'pointer',
                transition: 'background-color 0.2s'
              }}
              onMouseEnter={(e) => e.target.style.backgroundColor = 'rgba(124, 58, 237, 1)'}
              onMouseLeave={(e) => e.target.style.backgroundColor = 'rgba(124, 58, 237, 0.8)'}
            >
              Unlock
            </button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="chat-terminal" style={{ 
      height: '100%', 
      display: 'flex', 
      flexDirection: 'column',
      backgroundColor: 'transparent',
      position: 'relative',
      overflow: 'hidden'
    }}>
      {/* Header with Agent Dropdowns */}
      <div style={{
        padding: '16px 24px',
        borderBottom: '1px solid rgba(255, 255, 255, 0.1)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        gap: '16px',
        backgroundColor: 'rgba(20, 20, 20, 0.8)',
        backdropFilter: 'blur(10px)',
        zIndex: 10
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <div style={{ 
              width: '20px', 
              height: '20px', 
              backgroundColor: '#7c3aed', 
              borderRadius: '4px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#fff',
              fontSize: '0.7rem',
              fontWeight: 600
            }}>AI</div>
            <div style={{ position: 'relative' }}>
              <button
                type="button"
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: '#e5e5e5',
                  fontSize: '0.9rem',
                  fontWeight: 500,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                  padding: '4px 8px',
                  borderRadius: '4px',
                  transition: 'background-color 0.2s'
                }}
                onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.1)'}
                onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
              >
                GPT-5
                <span style={{ fontSize: '0.7rem', color: '#a3a3a3' }}>▼</span>
              </button>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <div style={{ 
              width: '20px', 
              height: '20px', 
              backgroundColor: '#7c3aed', 
              borderRadius: '4px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#fff',
              fontSize: '0.7rem',
              fontWeight: 600
            }}>AI</div>
            <div style={{ position: 'relative' }}>
              <button
                type="button"
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: '#e5e5e5',
                  fontSize: '0.9rem',
                  fontWeight: 500,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                  padding: '4px 8px',
                  borderRadius: '4px',
                  transition: 'background-color 0.2s'
                }}
                onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.1)'}
                onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
              >
                Sonnet 4.5
                <span style={{ fontSize: '0.7rem', color: '#a3a3a3' }}>▼</span>
              </button>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <div style={{ 
              width: '20px', 
              height: '20px', 
              backgroundColor: '#7c3aed', 
              borderRadius: '4px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#fff',
              fontSize: '0.7rem',
              fontWeight: 600
            }}>AI</div>
            <div style={{ position: 'relative' }}>
              <button
                type="button"
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: '#e5e5e5',
                  fontSize: '0.9rem',
                  fontWeight: 500,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                  padding: '4px 8px',
                  borderRadius: '4px',
                  transition: 'background-color 0.2s'
                }}
                onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.1)'}
                onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
              >
                GPT-4o
                <span style={{ fontSize: '0.7rem', color: '#a3a3a3' }}>▼</span>
              </button>
            </div>
          </div>
        </div>
        <span 
          key={isCollaborateMode ? 'collaborate' : 'solo'}
          className="mode-text-transition"
          style={{ 
            fontSize: '0.9rem', 
            color: isCollaborateMode ? '#a78bfa' : '#a3a3a3', 
            transition: 'color 0.4s ease-in-out',
            display: 'inline-block',
            marginRight: '30px'
          }}
        >
          {isCollaborateMode ? 'Collaborate Mode' : 'Solo Mode'}
        </span>
      </div>

      {/* Chat content with higher z-index */}
      <div 
        ref={messagesContainerRef}
        onScroll={checkScrollPosition}
        className="chat-messages-container"
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '20px 25px 20px 20px',
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

          {/* Always show "What would you like to do?" but fade when user types */}
          {!historyLoading && !historyError && (
            <div style={{ 
              color: '#a3a3a3', 
              fontSize: '2rem', 
              textAlign: 'center', 
              position: 'absolute',
              top: '50%',
              left: '50%',
              transform: 'translate(-50%, -50%)',
              fontWeight: 400,
              opacity: (inputValue.trim() || sessionStartTime) ? 0 : 1,
              transition: 'opacity 0.3s ease-in-out',
              pointerEvents: 'none',
              zIndex: 0
            }}>
              What would you like to do?
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

          {(() => {
            // Filter messages to only show those from current session
            let sessionMessages = sessionStartTime 
              ? messages.filter(msg => {
                  const msgTime = msg.timestamp instanceof Date ? msg.timestamp : new Date(msg.timestamp);
                  return msgTime >= sessionStartTime;
                })
              : [];

            // Filter by task ID if first task ID is set
            if (firstTaskId) {
              sessionMessages = sessionMessages.filter(msg => {
                // Include user messages (they should always be shown in chronological order)
                if (msg.sender === 'user') return true;
                // Include system messages without task IDs
                if (!msg.taskId) return true;
                // Include messages with task IDs >= first task ID
                const msgTaskId = parseInt(msg.taskId) || 0;
                return msgTaskId >= firstTaskId;
              });
            }

            if (sessionMessages.length === 0) {
              return null;
            }

            return sessionMessages.map((message) => {
            // Updated color mapping for dark purple theme
            // Using darker backgrounds with purple accents
            const agentColors = {
              'agent1': { bg: 'rgba(6, 78, 59, 0.4)', text: '#34d399', name: 'GPT-5', emoji: '🤖', border: '#065f46' },
              'agent2': { bg: 'rgba(30, 64, 175, 0.4)', text: '#60a5fa', name: 'Sonnet 4.5', emoji: '🦾', border: '#1e40af' },
              'agent3': { bg: 'rgba(124, 58, 237, 0.3)', text: '#a78bfa', name: 'GPT-4o', emoji: '🧠', border: '#6d28d9' },
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
            });
          })()}
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

      <div 
        ref={composerRef} 
        style={{
          padding: '24px',
          width: '100%',
          display: 'flex',
          justifyContent: 'center',
          background: 'linear-gradient(to top, #0a0a0a 80%, transparent)',
          paddingBottom: '40px',
          zIndex: 1,
          position: 'relative'
        }}
      >
        {!sessionStartTime && (
          <Aurora
            colorStops={["#7c3aed", "#a78bfa", "#7c3aed"]}
            blend={0.6}
            amplitude={0.8}
            speed={inputValue.trim() ? 0 : 0.5}
            opacity={inputValue.trim() ? 0 : 0.3}
          />
        )}
        <div style={{
          maxWidth: '800px',
          width: '100%',
          display: 'flex',
          flexDirection: 'column',
          gap: '12px',
          position: 'relative',
          zIndex: 1
        }}>
          <form onSubmit={handleSubmit} style={{
            width: '100%',
            position: 'relative',
            display: 'flex',
            flexDirection: 'column',
            gap: '8px'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div style={{ position: 'relative' }}>
                {isHoveringModeButton && (
                  <div style={{
                    position: 'absolute',
                    bottom: '100%',
                    left: '50%',
                    transform: 'translateX(-50%)',
                    marginBottom: '8px',
                    padding: '10px 14px',
                    backgroundColor: 'rgba(20, 20, 20, 1)',
                    color: '#e5e5e5',
                    fontSize: '0.85rem',
                    borderRadius: '8px',
                    border: '1px solid rgba(255, 255, 255, 0.1)',
                    boxShadow: '0 4px 12px rgba(0, 0, 0, 0.4)',
                    zIndex: 1000,
                    pointerEvents: 'none',
                    opacity: 0.8,
                    width: '240px',
                    textAlign: 'center',
                    lineHeight: '1.4'
                  }}>
                    {isCollaborateMode 
                      ? 'Collaborate: Agents work together to complete a given task'
                      : 'Solo: Agents compete to do the same task'
                    }
                  </div>
                )}
                <button
                  type="button"
                  onClick={() => setIsCollaborateMode(!isCollaborateMode)}
                  onMouseEnter={() => setIsHoveringModeButton(true)}
                  onMouseLeave={() => setIsHoveringModeButton(false)}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    cursor: 'pointer',
                    padding: '8px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    transition: 'all 0.3s',
                    opacity: isCollaborateMode ? 1 : 0.4,
                    filter: isCollaborateMode ? 'none' : 'grayscale(100%)'
                  }}
                >
                  <img 
                    src={collaborateIcon} 
                    alt="Collaborate Mode" 
                    style={{
                      width: '50px',
                      height: '50px',
                      objectFit: 'overflow'
                    }}
                  />
                </button>
              </div>
              <input
                type="text"
                ref={inputRef}
                value={inputValue}
                onChange={handleInputChange}
                onSelect={handleInputSelect}
                onKeyUp={handleInputSelect}
                placeholder={isAuthenticated ? "Ask anything..." : "Authenticate to send messages"}
                disabled={!isAuthenticated || isLoading}
                style={{
                  flex: 1,
                  padding: '16px 50px 16px 20px',
                  backgroundColor: 'rgba(26, 26, 26, 0.8)',
                  border: '1px solid rgba(255, 255, 255, 0.1)',
                  borderRadius: '12px',
                  color: '#e5e5e5',
                  fontSize: '1rem',
                  outline: 'none',
                  boxShadow: '0 2px 8px rgba(0, 0, 0, 0.4)',
                  backdropFilter: 'blur(12px)',
                  marginLeft: '-0px'
                }}
              />
              <button
                type="submit"
                disabled={!isAuthenticated || !inputValue.trim() || isLoading}
                style={{
                  background: inputValue.trim() ? '#7c3aed' : 'transparent',
                  color: inputValue.trim() ? '#ffffff' : '#737373',
                  border: 'none',
                  borderRadius: '8px',
                  width: '40px',
                  height: '40px',
                  cursor: inputValue.trim() ? 'pointer' : 'default',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transition: 'all 0.2s',
                  boxShadow: inputValue.trim() ? '0 0 15px rgba(124, 58, 237, 0.4)' : 'none'
                }}
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="22" y1="2" x2="11" y2="13"></line>
                  <path d="M22 2L15 22 11 13 2 9 22 2z"></path>
                </svg>
              </button>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', paddingLeft: '66px' }}>
              <button
                type="button"
                style={{
                  width: '32px',
                  height: '32px',
                  borderRadius: '6px',
                  border: 'none',
                  background: 'rgba(255, 255, 255, 0.05)',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '1.2rem',
                  transition: 'background-color 0.2s'
                }}
                onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.1)'}
                onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.05)'}
                title="Search"
              >
                🌐
              </button>
              <button
                type="button"
                style={{
                  width: '32px',
                  height: '32px',
                  borderRadius: '6px',
                  border: 'none',
                  background: 'rgba(255, 255, 255, 0.05)',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '1.2rem',
                  transition: 'background-color 0.2s'
                }}
                onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.1)'}
                onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.05)'}
                title="Image"
              >
                🖼️
              </button>
              <button
                type="button"
                style={{
                  width: '32px',
                  height: '32px',
                  borderRadius: '6px',
                  border: 'none',
                  background: 'rgba(255, 255, 255, 0.05)',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '1.2rem',
                  transition: 'background-color 0.2s'
                }}
                onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.1)'}
                onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.05)'}
                title="Code"
              >
                &lt;&gt;
              </button>
            </div>
          </form>
        </div>
        {isMentionMenuVisible && mentionOptions.length > 0 && (
          <div
            style={{
              position: 'absolute',
              left: mentionCoords.left,
              top: mentionCoords.top,
              width: '320px',
              backgroundColor: 'rgba(15, 15, 20, 0.98)',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              borderRadius: '12px',
              padding: '10px 0',
              display: 'flex',
              flexDirection: 'column',
              gap: '4px',
              boxShadow: '0 12px 32px rgba(0,0,0,0.6)',
              zIndex: 5,
              transform: isMentionMenuVisible ? 'translateY(calc(-100% - 12px))' : 'translateY(calc(-100% - 2px))',
              opacity: isMentionMenuVisible ? 1 : 0,
              transition: 'opacity 0.15s ease, transform 0.15s ease'
            }}
          >
            <div style={{ padding: '0 16px', fontSize: '0.75rem', letterSpacing: '0.05em', color: '#9ca3af' }}>
              AGENTS
            </div>
            {mentionOptions.map((agentId) => {
              const status = resolvedStatus(agentId);
              const isOnline = status === 'online';
              const handleMouseDown = (e) => {
                e.preventDefault();
                insertMention(agentId);
              };
              return (
                <button
                  key={agentId}
                  type="button"
                  onMouseDown={handleMouseDown}
                  style={{
                    padding: '10px 16px',
                    border: 'none',
                    background: 'transparent',
                    display: 'flex',
                    width: '100%',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    color: '#e5e5e5',
                    cursor: 'pointer'
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <div
                      style={{
                        width: '36px',
                        height: '36px',
                        borderRadius: '50%',
                        background: 'linear-gradient(135deg, #1f2937, #111827)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: '1rem',
                        textTransform: 'uppercase',
                        color: '#c4c4c4',
                        border: '1px solid rgba(255,255,255,0.08)'
                      }}
                    >
                      {agentId.replace('agent', 'A')}
                    </div>
                    <div style={{ textAlign: 'left' }}>
                      <div style={{ fontWeight: 600, color: '#f3f4f6' }}>
                        {agentId === 'agent1' ? 'GPT-5' : agentId === 'agent2' ? 'Sonnet 4.5' : agentId === 'agent3' ? 'GPT-4o' : agentId}
                      </div>
                      <div style={{ fontSize: '0.75rem', color: '#9ca3af' }}>
                        {isOnline ? 'Ready for tasks' : 'Agent unreachable'}
                      </div>
                    </div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span
                      style={{
                        width: '8px',
                        height: '8px',
                        borderRadius: '50%',
                        backgroundColor: isOnline ? '#34d399' : '#f87171'
                      }}
                    />
                    <span style={{ fontSize: '0.8rem', color: isOnline ? '#d1fae5' : '#fecaca' }}>
                      {isOnline ? 'online' : 'offline'}
                    </span>
                  </div>
                </button>
              );
            })}
            <div style={{ padding: '8px 16px 0 16px', fontSize: '0.7rem', color: '#6b7280', borderTop: '1px solid rgba(255,255,255,0.05)' }}>
              Click or keep typing to notify agents with access.
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default ChatTerminal;
