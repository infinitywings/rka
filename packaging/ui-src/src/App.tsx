import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

interface SidecarStatus {
  running: boolean;
  pid: number | null;
  consecutive_failures: number;
}

export default function App() {
  const [status, setStatus] = useState<SidecarStatus | null>(null);
  const [backendUrl, setBackendUrl] = useState<string>("");
  const [healthy, setHealthy] = useState<boolean | null>(null);

  useEffect(() => {
    invoke<string>("get_backend_url").then(setBackendUrl).catch(() => {});

    const refresh = () => {
      invoke<SidecarStatus>("sidecar_status").then(setStatus).catch(() => {});
    };
    refresh();
    const id = setInterval(refresh, 2000);

    const unlisten = listen("sidecar-unhealthy", () => setHealthy(false));
    const unlistenStarted = listen("sidecar-started", () => setHealthy(true));

    return () => {
      clearInterval(id);
      unlisten.then((fn) => fn()).catch(() => {});
      unlistenStarted.then((fn) => fn()).catch(() => {});
    };
  }, []);

  useEffect(() => {
    if (!backendUrl) return;
    fetch(`${backendUrl}/api/health`)
      .then((r) => setHealthy(r.ok))
      .catch(() => setHealthy(false));
  }, [backendUrl, status?.pid]);

  return (
    <main style={styles.shell}>
      <header style={styles.header}>
        <h1 style={styles.title}>RKA — Research Knowledge Agent</h1>
        <p style={styles.tagline}>
          A self-contained research knowledge base that bridges to MCP-capable
          coding agents (Claude Desktop, Claude Code, Cursor, VSCode-Copilot,
          Codex, Antigravity).
        </p>
      </header>

      <section style={styles.panel}>
        <h2 style={styles.panelTitle}>Sidecar status</h2>
        <dl style={styles.dl}>
          <dt>Running</dt>
          <dd>{status?.running ? "yes" : "no"}</dd>
          <dt>PID</dt>
          <dd>{status?.pid ?? "—"}</dd>
          <dt>Backend</dt>
          <dd>
            {backendUrl}
            {healthy === true && <span style={styles.ok}> ✓</span>}
            {healthy === false && <span style={styles.bad}> ✗</span>}
          </dd>
          <dt>Consecutive failures</dt>
          <dd>{status?.consecutive_failures ?? 0}</dd>
        </dl>
      </section>

      <section style={styles.panel}>
        <h2 style={styles.panelTitle}>Onboarding</h2>
        <p style={styles.muted}>
          The 7-client onboarding grid (D3) and Settings tab (D4) will render
          here. This scaffold reaches the live sidecar and reports its health
          status; the per-client merger UI ships in the next deliverable.
        </p>
      </section>
    </main>
  );
}

const styles: Record<string, React.CSSProperties> = {
  shell: {
    fontFamily:
      "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Inter', sans-serif",
    maxWidth: 880,
    margin: "0 auto",
    padding: "32px 24px",
    color: "#1a1a1a",
  },
  header: {
    marginBottom: 32,
  },
  title: {
    fontSize: 24,
    fontWeight: 600,
    margin: 0,
  },
  tagline: {
    marginTop: 6,
    fontSize: 14,
    color: "#4a4a4a",
    lineHeight: 1.5,
  },
  panel: {
    border: "1px solid #e3e3e3",
    borderRadius: 8,
    padding: 16,
    marginBottom: 16,
    background: "#fafafa",
  },
  panelTitle: {
    fontSize: 16,
    fontWeight: 600,
    margin: "0 0 12px 0",
  },
  dl: {
    display: "grid",
    gridTemplateColumns: "180px 1fr",
    rowGap: 6,
    columnGap: 12,
    margin: 0,
    fontSize: 13,
  },
  muted: {
    fontSize: 13,
    color: "#4a4a4a",
    margin: 0,
  },
  ok: { color: "#138a36" },
  bad: { color: "#c1382b" },
};
