export const ensureDate = (val) => {
  if (val instanceof Date) return val;
  if (typeof val === 'string' || typeof val === 'number') {
    const d = new Date(val);
    return isNaN(d.getTime()) ? new Date() : d;
  }
  return new Date();
};

export const normalizePercent = (val) => {
  if (val == null || val === '') return null;
  const num = parseFloat(val);
  if (isNaN(num)) return null;
  return Math.max(0, Math.min(100, num));
};

export const formatPercentLabel = (val) => {
  const p = normalizePercent(val);
  return p !== null ? `${Math.round(p)}%` : null;
};

export const formatTime = (date) => {
  if (!date) {
    return '—';
  }
  const safeDate = ensureDate(date);
  // Format time in EST timezone with explicit timezone display
  return safeDate.toLocaleTimeString('en-US', { 
    hour: '2-digit', 
    minute: '2-digit',
    second: '2-digit',
    timeZone: 'America/New_York',
    timeZoneName: 'short'
  });
};

export const buildAgentMessage = (item) => {
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

