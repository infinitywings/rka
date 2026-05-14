import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { writeText } from "@tauri-apps/plugin-clipboard-manager";

import { styles } from "../styles";

const REFRESH_INTERVAL_MS = 500;
const TAIL_LINES = 200;

export function LogsPanel() {
  const [lines, setLines] = useState<string[]>([]);
  const [paused, setPaused] = useState<boolean>(false);
  const [copyStatus, setCopyStatus] = useState<string>("");
  const tailRef = useRef<HTMLPreElement | null>(null);

  const fetchTail = useCallback(async () => {
    try {
      const next = await invoke<string[]>("tail_server_log", { n: TAIL_LINES });
      setLines(next);
    } catch (e) {
      setLines([`(error reading log: ${e})`]);
    }
  }, []);

  useEffect(() => {
    if (paused) return;
    fetchTail();
    const id = setInterval(fetchTail, REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [paused, fetchTail]);

  useEffect(() => {
    const el = tailRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines]);

  const handleShowInFinder = useCallback(async () => {
    try {
      await invoke("show_logs_in_finder");
    } catch (e) {
      setCopyStatus(`Cannot reveal log: ${e}`);
    }
  }, []);

  const handleCopyDiagnostic = useCallback(async () => {
    setCopyStatus("Assembling…");
    try {
      const blob = await invoke<string>("copy_diagnostic_blob");
      await writeText(blob);
      setCopyStatus(
        `Diagnostic info copied to clipboard (${blob.length.toLocaleString()} chars). Paste into your issue report.`,
      );
    } catch (e) {
      setCopyStatus(`Copy failed: ${e}`);
    }
  }, []);

  return (
    <section style={styles.panel}>
      <h2 style={styles.panelTitle}>Logs</h2>
      <p style={styles.muted}>
        Tail of <code>~/Library/Logs/RKA/server.log</code> — auto-refresh every
        500 ms. The diagnostic-copy command bundles app + sidecar + OS metadata,
        the 7-client status matrix, redacted health + capabilities JSON, DB
        schema state, and the last 100 log lines into a plaintext blob your
        clipboard receives. <strong>No telemetry transmits.</strong>
      </p>

      <div style={styles.globalActions}>
        <button
          style={styles.secondaryBtn}
          onClick={() => setPaused((p) => !p)}
          type="button"
        >
          {paused ? "Resume" : "Pause"}
        </button>
        <button
          style={styles.secondaryBtn}
          onClick={handleShowInFinder}
          type="button"
        >
          Show logs in Finder
        </button>
        <button
          style={styles.primaryBtn}
          onClick={handleCopyDiagnostic}
          type="button"
        >
          Copy diagnostic info
        </button>
      </div>
      {copyStatus && <div style={styles.muted}>{copyStatus}</div>}

      <pre ref={tailRef} style={tailStyle}>
        {lines.length === 0 ? "(log is empty)" : lines.join("\n")}
      </pre>
    </section>
  );
}

const tailStyle: React.CSSProperties = {
  marginTop: 12,
  padding: 12,
  background: "#0f1115",
  color: "#dde1e6",
  borderRadius: 6,
  fontFamily: "ui-monospace, monospace",
  fontSize: 11,
  maxHeight: 360,
  overflow: "auto",
  whiteSpace: "pre",
};
