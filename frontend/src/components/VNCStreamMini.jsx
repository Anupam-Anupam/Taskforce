import { useEffect } from 'react';

/**
 * VNC Stream Component - Direct iframe embedding
 */
const VNCStreamMini = ({ agentId, vncUrl }) => {
  // Default URLs per agent
  const defaultUrls = {
    'agent1': 'https://m-linux-aqnzbmas97.containers.cloud.trycua.com/vnc.html?autoconnect=true&password=479e9bdb455b566d',
    'agent2': 'https://m-linux-kpzcblkosd.containers.cloud.trycua.com/vnc.html?autoconnect=true&password=4b1478417d084de2',
    'agent3': 'https://l-linux-3iouwxahdd.containers.cloud.trycua.com/vnc.html?autoconnect=true&password=248458781f94801e'
  };
  
  const embedUrl = vncUrl || defaultUrls[agentId];

  useEffect(() => {
    console.log(`[${agentId}] VNC URL:`, embedUrl);
  }, [embedUrl, agentId]);

  return (
    <div className="vnc-stream-mini">
      <iframe
        src={embedUrl}
        title={`${agentId} Live VNC Stream`}
        className="vnc-stream-mini__iframe"
        allow="clipboard-read; clipboard-write"
      />
    </div>
  );
};

export default VNCStreamMini;

