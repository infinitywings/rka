import { useCallback, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

import { styles } from "../styles";

interface Props {
  /** Called when the user clicks Refresh; should re-fetch detection state. */
  onRefresh: () => Promise<void>;
  /** Called when the user dismisses the install-assist step. */
  onSkip: () => void;
}

const DOWNLOAD_URL = "https://claude.ai/download";

/**
 * D9 — Link-only install-assist for Claude Desktop.
 *
 * Surfaced ABOVE the 7-client onboarding grid when the Claude Desktop
 * detection probe returns negative. Per PI ratification 2026-05-13
 * (jrn_01KRH6Z85PEXHG1JTH7MQQM0GH), this is strictly link-only:
 * - opens https://claude.ai/download in the user's default browser via
 *   the `open_external_url` Tauri command (which guards http(s) only);
 * - does NOT programmatically download, mount, or invoke any installer
 *   (Mac users expect to fetch installers themselves, and auto-install
 *   would surface confusing Gatekeeper warnings).
 *
 * The user clicks Refresh after completing the manual install to re-run
 * the detection probe; Skip dismisses the step so the rest of the
 * onboarding flow can continue without Claude Desktop.
 */
export function ClaudeDesktopInstallAssist({ onRefresh, onSkip }: Props) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const handleOpen = useCallback(async () => {
    try {
      await invoke("open_external_url", { url: DOWNLOAD_URL });
    } catch (e) {
      setMessage(`Could not open download page: ${e}`);
    }
  }, []);

  const handleRefresh = useCallback(async () => {
    setBusy(true);
    setMessage("Re-probing for Claude Desktop…");
    try {
      await onRefresh();
      setMessage("Refreshed — if Claude Desktop is installed, it should appear in the list below.");
    } catch (e) {
      setMessage(`Refresh failed: ${e}`);
    } finally {
      setBusy(false);
    }
  }, [onRefresh]);

  return (
    <section style={assistStyles.panel}>
      <h2 style={styles.panelTitle}>Claude Desktop not detected</h2>
      <p style={styles.muted}>
        Claude Desktop is Anthropic's standalone app for chatting with Claude.
        RKA configures it to use this local knowledge base as an MCP server, so
        Claude can look up your research notes, decisions, and missions
        directly during a conversation.
      </p>
      <p style={styles.muted}>
        If you'd like to use it, download from the official page below. RKA
        does <strong>not</strong> install Claude Desktop for you — Mac
        Gatekeeper expects you to fetch installers yourself.
      </p>
      <div style={styles.globalActions}>
        <button
          style={styles.primaryBtn}
          onClick={handleOpen}
          type="button"
        >
          Open download page
        </button>
        <button
          style={styles.secondaryBtn}
          onClick={handleRefresh}
          disabled={busy}
          type="button"
        >
          {busy ? "Refreshing…" : "Refresh"}
        </button>
        <button
          style={styles.secondaryBtn}
          onClick={onSkip}
          type="button"
        >
          Skip
        </button>
      </div>
      {message && <div style={styles.muted}>{message}</div>}
    </section>
  );
}

const assistStyles = {
  panel: {
    ...styles.panel,
    borderColor: "#e9d4a2",
    background: "#fffaf0",
  } as React.CSSProperties,
};
