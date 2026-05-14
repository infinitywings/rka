import { useCallback, useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

interface SidecarStatus {
  running: boolean;
  pid: number | null;
  consecutive_failures: number;
}

interface ProbeResult {
  detected: boolean;
  evidence: string[];
}

interface ClientSummary {
  id: string;
  display_name: string;
  format: "json" | "toml";
  detection: ProbeResult;
  config_path: string | null;
}

interface MergeResult {
  config_path: string;
  backup_path: string | null;
  previous_rka_command: string | null;
  new_rka_command: string;
}

interface VerifyResult {
  config_syntax_ok: boolean;
  rka_entry_present: boolean;
  backend_reachable: boolean;
  capabilities_reachable: boolean;
  reason: string | null;
}

interface MergeSummary {
  client_id: string;
  result: MergeResult | null;
  error: string | null;
}

type View = "onboarding" | "status";

export default function App() {
  const [view, setView] = useState<View>("onboarding");
  const [status, setStatus] = useState<SidecarStatus | null>(null);
  const [backendUrl, setBackendUrl] = useState<string>("");
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [clients, setClients] = useState<ClientSummary[]>([]);
  const [showUndetected, setShowUndetected] = useState<boolean>(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [verifyState, setVerifyState] = useState<Record<string, VerifyResult>>({});
  const [mergeOutcome, setMergeOutcome] = useState<MergeSummary[] | null>(null);
  const [isMerging, setIsMerging] = useState<boolean>(false);

  useEffect(() => {
    invoke<string>("get_backend_url").then(setBackendUrl).catch(() => {});
    const refresh = () => {
      invoke<SidecarStatus>("sidecar_status").then(setStatus).catch(() => {});
    };
    refresh();
    const id = setInterval(refresh, 2000);
    const unhealthy = listen("sidecar-unhealthy", () => setHealthy(false));
    const started = listen("sidecar-started", () => setHealthy(true));
    return () => {
      clearInterval(id);
      unhealthy.then((fn) => fn()).catch(() => {});
      started.then((fn) => fn()).catch(() => {});
    };
  }, []);

  useEffect(() => {
    if (!backendUrl) return;
    fetch(`${backendUrl}/api/health`)
      .then((r) => setHealthy(r.ok))
      .catch(() => setHealthy(false));
  }, [backendUrl, status?.pid]);

  useEffect(() => {
    invoke<ClientSummary[]>("list_mcp_clients")
      .then((list) => {
        setClients(list);
        const detected = new Set(
          list.filter((c) => c.detection.detected).map((c) => c.id),
        );
        setSelected(detected);
      })
      .catch(() => {});
  }, []);

  const detectedClients = useMemo(
    () => clients.filter((c) => c.detection.detected),
    [clients],
  );
  const undetectedClients = useMemo(
    () => clients.filter((c) => !c.detection.detected),
    [clients],
  );

  const toggleClient = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const runMerge = useCallback(async () => {
    setIsMerging(true);
    setMergeOutcome(null);
    try {
      const out = await invoke<MergeSummary[]>("merge_mcp_clients", {
        ids: Array.from(selected),
      });
      setMergeOutcome(out);
      await invoke<string>("rewrite_launcher").catch(() => "");
      const verifyIds = out.filter((m) => m.error === null).map((m) => m.client_id);
      const pairs = await invoke<[string, VerifyResult][]>(
        "verify_all_mcp_clients",
        { ids: verifyIds },
      );
      setVerifyState(Object.fromEntries(pairs));
    } catch (e) {
      setMergeOutcome([
        { client_id: "_", result: null, error: String(e) },
      ]);
    } finally {
      setIsMerging(false);
    }
  }, [selected]);

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
            style={view === "status" ? styles.navActive : styles.navBtn}
            onClick={() => setView("status")}
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
        <section style={styles.panel}>
          <h2 style={styles.panelTitle}>Connect your coding agents</h2>
          <p style={styles.muted}>
            RKA can register itself as an MCP server in seven supported clients.
            Detected installs are pre-selected — toggle the checkboxes to control
            which configs get touched.
          </p>

          <div style={styles.grid}>
            {detectedClients.map((c) => (
              <ClientRow
                key={c.id}
                client={c}
                checked={selected.has(c.id)}
                onToggle={() => toggleClient(c.id)}
                verify={verifyState[c.id]}
              />
            ))}
          </div>

          <button
            style={styles.toggleAll}
            onClick={() => setShowUndetected((p) => !p)}
          >
            {showUndetected
              ? `Hide ${undetectedClients.length} not-installed clients`
              : `Show all (${undetectedClients.length} not-installed)`}
          </button>

          {showUndetected && undetectedClients.length > 0 && (
            <div style={{ ...styles.grid, opacity: 0.65 }}>
              {undetectedClients.map((c) => (
                <ClientRow
                  key={c.id}
                  client={c}
                  checked={selected.has(c.id)}
                  onToggle={() => toggleClient(c.id)}
                  verify={verifyState[c.id]}
                />
              ))}
            </div>
          )}

          <div style={styles.actionBar}>
            <button
              style={styles.primaryBtn}
              disabled={selected.size === 0 || isMerging}
              onClick={runMerge}
            >
              {isMerging
                ? "Installing…"
                : `Install on ${selected.size} client${selected.size === 1 ? "" : "s"}`}
            </button>
            {mergeOutcome && (
              <div style={styles.outcomeBlock}>
                {mergeOutcome.map((m) => (
                  <div key={m.client_id} style={styles.outcomeRow}>
                    <strong>{m.client_id}</strong>:{" "}
                    {m.error ? (
                      <span style={styles.bad}>✗ {m.error}</span>
                    ) : (
                      <span style={styles.ok}>
                        ✓ wrote to {m.result?.config_path}
                        {m.result?.backup_path && (
                          <span style={styles.muted}>
                            {" "}
                            (backup: {m.result.backup_path})
                          </span>
                        )}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>
      )}
    </main>
  );
}

interface ClientRowProps {
  client: ClientSummary;
  checked: boolean;
  onToggle: () => void;
  verify: VerifyResult | undefined;
}

function ClientRow({ client, checked, onToggle, verify }: ClientRowProps) {
  return (
    <label style={styles.row}>
      <input type="checkbox" checked={checked} onChange={onToggle} />
      <div style={styles.rowBody}>
        <div style={styles.rowName}>
          {client.display_name}
          <span style={styles.formatTag}>{client.format}</span>
          {client.detection.detected && <span style={styles.detected}> detected</span>}
        </div>
        {client.config_path && (
          <div style={styles.rowPath}>{client.config_path}</div>
        )}
        {verify && (
          <div style={styles.verifyRow}>
            <Pill ok={verify.config_syntax_ok} label="config" />
            <Pill ok={verify.rka_entry_present} label="rka entry" />
            <Pill ok={verify.backend_reachable} label="backend" />
            <Pill ok={verify.capabilities_reachable} label="capabilities" />
            {verify.reason && <span style={styles.muted}>{verify.reason}</span>}
          </div>
        )}
      </div>
    </label>
  );
}

function Pill({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span style={{ ...styles.pill, background: ok ? "#e6f4ea" : "#fdecea", color: ok ? "#137333" : "#a50e0e" }}>
      {ok ? "✓" : "✗"} {label}
    </span>
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
  header: { marginBottom: 24 },
  title: { fontSize: 24, fontWeight: 600, margin: 0 },
  tagline: { marginTop: 6, fontSize: 14, color: "#4a4a4a", lineHeight: 1.5 },
  nav: { display: "flex", gap: 4, marginTop: 16 },
  navBtn: {
    background: "transparent",
    border: "1px solid #e3e3e3",
    borderRadius: 6,
    padding: "6px 12px",
    fontSize: 13,
    cursor: "pointer",
  },
  navActive: {
    background: "#1a1a1a",
    color: "#fff",
    border: "1px solid #1a1a1a",
    borderRadius: 6,
    padding: "6px 12px",
    fontSize: 13,
    cursor: "pointer",
  },
  panel: {
    border: "1px solid #e3e3e3",
    borderRadius: 8,
    padding: 16,
    marginBottom: 16,
    background: "#fafafa",
  },
  panelTitle: { fontSize: 16, fontWeight: 600, margin: "0 0 12px 0" },
  dl: {
    display: "grid",
    gridTemplateColumns: "180px 1fr",
    rowGap: 6,
    columnGap: 12,
    margin: 0,
    fontSize: 13,
  },
  muted: { fontSize: 12, color: "#6a6a6a" },
  grid: { display: "flex", flexDirection: "column", gap: 8, marginTop: 12 },
  row: {
    display: "flex",
    alignItems: "flex-start",
    gap: 12,
    padding: 10,
    border: "1px solid #ececec",
    borderRadius: 6,
    background: "#fff",
    cursor: "pointer",
  },
  rowBody: { display: "flex", flexDirection: "column", gap: 4, flex: 1 },
  rowName: { fontSize: 14, fontWeight: 500, display: "flex", alignItems: "center", gap: 8 },
  formatTag: {
    fontSize: 10,
    background: "#f0f0f0",
    padding: "1px 6px",
    borderRadius: 3,
    color: "#6a6a6a",
    textTransform: "uppercase",
  },
  detected: { fontSize: 11, color: "#137333", marginLeft: 4 },
  rowPath: { fontSize: 11, color: "#6a6a6a", fontFamily: "ui-monospace, monospace" },
  verifyRow: { display: "flex", gap: 6, marginTop: 4, flexWrap: "wrap", alignItems: "center" },
  pill: {
    fontSize: 10,
    padding: "2px 6px",
    borderRadius: 10,
    fontWeight: 500,
  },
  toggleAll: {
    background: "transparent",
    border: "none",
    color: "#1a73e8",
    padding: 0,
    marginTop: 12,
    cursor: "pointer",
    fontSize: 12,
  },
  actionBar: { marginTop: 16, display: "flex", flexDirection: "column", gap: 12 },
  primaryBtn: {
    background: "#1a73e8",
    color: "#fff",
    border: "none",
    borderRadius: 6,
    padding: "8px 16px",
    fontSize: 14,
    cursor: "pointer",
    alignSelf: "flex-start",
  },
  outcomeBlock: {
    border: "1px solid #e3e3e3",
    borderRadius: 6,
    padding: 12,
    background: "#fff",
    fontSize: 12,
    display: "flex",
    flexDirection: "column",
    gap: 4,
  },
  outcomeRow: {},
  ok: { color: "#137333" },
  bad: { color: "#a50e0e" },
};
