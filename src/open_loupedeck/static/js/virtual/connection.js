/*
 * virtual/connection.js — WebSocket link to the virtual device (/ws/virtual) with automatic
 * reconnection. Protocol: see devices/virtual/transport.py and docs/virtual-device.md.
 *
 *   const link = connectVirtual({ url, onMessage(msg), onStatus(status, code) });
 *   link.send({ t: "event", id, type, value })  -> true when sent, false when offline
 *   link.close()
 *
 * Statuses: "connecting" | "open" | "closed" (will retry) | "none" (the agent has no virtual
 * device; retries every 1.5 s).
 */

const CLOSE_NO_DEVICE = 1013;

export function defaultSocketUrl() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/ws/virtual`;
}

export function connectVirtual({ url = defaultSocketUrl(), onMessage, onStatus }) {
  let ws = null;
  let timer = 0;
  let attempt = 0;
  let stopped = false;

  function schedule(slow) {
    if (stopped) return;
    const delay = slow ? 1500 : Math.min(3000, 250 * 1.6 ** attempt);
    attempt += 1;
    timer = window.setTimeout(open, delay);
  }

  function open() {
    if (stopped) return;
    onStatus("connecting");
    let sock;
    try {
      sock = new WebSocket(url);
    } catch {
      onStatus("closed");
      schedule(false);
      return;
    }
    ws = sock;
    sock.onopen = () => {
      attempt = 0;
      onStatus("open");
    };
    sock.onmessage = (e) => {
      let msg = null;
      try {
        msg = JSON.parse(e.data);
      } catch {
        return;
      }
      if (msg && typeof msg === "object") onMessage(msg);
    };
    sock.onclose = (e) => {
      if (ws === sock) ws = null;
      if (stopped) return;
      const none = e.code === CLOSE_NO_DEVICE;
      onStatus(none ? "none" : "closed", e.code);
      schedule(none);
    };
    sock.onerror = () => {};
  }

  open();

  return {
    send(obj) {
      if (!ws || ws.readyState !== WebSocket.OPEN) return false;
      ws.send(JSON.stringify(obj));
      return true;
    },
    close() {
      stopped = true;
      window.clearTimeout(timer);
      if (ws) ws.close();
    },
  };
}
