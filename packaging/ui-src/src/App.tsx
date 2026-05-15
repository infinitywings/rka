import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

import { LogsPanel } from "./components/LogsPanel";
import { OnboardingPanel } from "./components/OnboardingPanel";
import { SettingsTab } from "./components/SettingsTab";
import { styles } from "./styles";
import { ClientSummary, SidecarStatus } from "./types";

type View = "onboarding" | "status" | "settings" | "logs";

export default function App() {
  const [view, setView] = useState<View>("onboarding");
  const [status, setStatus] = useState<SidecarStatus | null>(null);
  const [backendUrl, setBackendUrl] = useState<string>("");
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [clients, setClients] = useState<ClientSummary[]>([]);

  const refreshClients = useCallback(async () => {
    const list = await invoke<ClientSummary[]>("list_mcp_clients");
    setClients(list);
  }, []);

  useEffect(() => {
    invoke<string>("get_backend_url").then(setBackendUrl).catch(() => {});
    const refresh = () => {
      invoke<SidecarStatus>("sidecar_status").then(setStatus).catch(() => {});
    };
    refresh();
    const id = setInterval(refresh, 2000);
    const unhealthy = listen("sidecar-unhealthy", () => setHealthy(false));
    const started = listen("sidecar-started", () => setHealthy(true));
    refreshClients().catch(() => {});
    return () => {
      clearInterval(id);
      unhealthy.then((fn) => fn()).catch(() => {});
      started.then((fn) => fn()).catch(() => {});
    };
  }, [refreshClients]);

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
          coding agents. The desktop app runs the SQLite + FTS5 + sqlite-vec
          backend locally with no cloud dependencies.
        </p>
        <nav style={styles.nav}>
          <button
            style={view === "onboarding" ? styles.navActive : styles.navBtn}
            onClick={() => setView("onboarding")}
          >
            Onboarding
          </button>
          <button
            style={view === "settings" ? styles.navActive : styles.navBtn}
            onClick={() => setView("settings")}
          >
            Settings
          </button>
          <button
            style={view === "logs" ? styles.navActive : styles.navBtn}
            onClick={() => setView("logs")}
            type="button"
          >
            Logs
          </button>
          <button
            style={view === "status" ? styles.navActive : styles.navBtn}
            onClick={() => setView("status")}
            type="button"
          >
            Status
          </button>
        </nav>
      </header>

      {view === "status" && (
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
      )}

      {view === "onboarding" && (
        <OnboardingPanel
          clients={clients}
          backendUrl={backendUrl}
          onComplete={refreshClients}
        />
      )}

      {view === "settings" && (
        <SettingsTab clients={clients} refreshClients={refreshClients} />
      )}

      {view === "logs" && <LogsPanel />}
    </main>
  );
}
