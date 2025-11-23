import { useEffect } from 'react';

/**
 * VNC Stream Component - Direct iframe embedding
 */
const VNCStreamMini = ({ agentId, vncUrl }) => {
  // Default VNC URLs per agent
  const defaultUrls = {
    'agent1': 'https://m-linux-pyphfh77.sandbox.cua.ai/vnc.html?autoconnect=true&password=a1378b59f3dd8c19',
    'agent2': 'https://m-linux-kpzcblkosd.containers.cloud.trycua.com/vnc.html?autoconnect=true&password=4b1478417d084de2',
    'agent3': 'https://l-linux-3iouwxahdd.containers.cloud.trycua.com/vnc.html?autoconnect=true&password=248458781f94801e'
  };
  
  const baseUrl = vncUrl || defaultUrls[agentId];
  
  // Append resize=scale to ensure the remote screen scales to fit the iframe
  const separator = baseUrl.includes('?') ? '&' : '?';
  const embedUrl = baseUrl.includes('resize=scale') ? baseUrl : `${baseUrl}${separator}resize=scale`;

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

