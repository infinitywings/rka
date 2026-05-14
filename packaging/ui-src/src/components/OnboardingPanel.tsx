import { useCallback, useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

import { ClaudeDesktopInstallAssist } from "./ClaudeDesktopInstallAssist";
import { ClientRow } from "./ClientRow";
import { styles } from "../styles";
import { ClientSummary, MergeSummary, VerifyResult } from "../types";

interface Props {
  clients: ClientSummary[];
  /** Called after the merge action completes so the parent can refresh
   *  detection state. Also wired into the Claude Desktop install-assist
   *  Refresh button. */
  onComplete?: () => Promise<void> | void;
}

export function OnboardingPanel({ clients, onComplete }: Props) {
  const [showUndetected, setShowUndetected] = useState<boolean>(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [verifyState, setVerifyState] = useState<Record<string, VerifyResult>>({});
  const [mergeOutcome, setMergeOutcome] = useState<MergeSummary[] | null>(null);
  const [isMerging, setIsMerging] = useState<boolean>(false);
  const [skippedAssist, setSkippedAssist] = useState<boolean>(false);

  useEffect(() => {
    setSelected(
      new Set(clients.filter((c) => c.detection.detected).map((c) => c.id)),
    );
  }, [clients]);

  const detected = useMemo(
    () => clients.filter((c) => c.detection.detected),
    [clients],
  );
  const undetected = useMemo(
    () => clients.filter((c) => !c.detection.detected),
    [clients],
  );
  const claudeDesktop = useMemo(
    () => clients.find((c) => c.id === "claude_desktop"),
    [clients],
  );
  const showInstallAssist =
    claudeDesktop !== undefined &&
    !claudeDesktop.detection.detected &&
    !skippedAssist;

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
      const verifyIds = out
        .filter((m) => m.error === null)
        .map((m) => m.client_id);
      const pairs = await invoke<[string, VerifyResult][]>(
        "verify_all_mcp_clients",
        { ids: verifyIds },
      );
      setVerifyState(Object.fromEntries(pairs));
      onComplete?.();
    } catch (e) {
      setMergeOutcome([{ client_id: "_", result: null, error: String(e) }]);
    } finally {
      setIsMerging(false);
    }
  }, [selected, onComplete]);

  const handleAssistRefresh = useCallback(async () => {
    if (onComplete) {
      await onComplete();
    }
  }, [onComplete]);

  return (
    <>
      {showInstallAssist && (
        <ClaudeDesktopInstallAssist
          onRefresh={handleAssistRefresh}
          onSkip={() => setSkippedAssist(true)}
        />
      )}
      <section style={styles.panel}>
        <h2 style={styles.panelTitle}>Connect your coding agents</h2>
      <p style={styles.muted}>
        RKA can register itself as an MCP server in seven supported clients.
        Detected installs are pre-selected — toggle the checkboxes to control
        which configs get touched.
      </p>

      <div style={styles.grid}>
        {detected.map((c) => (
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
        type="button"
      >
        {showUndetected
          ? `Hide ${undetected.length} not-installed clients`
          : `Show all (${undetected.length} not-installed)`}
      </button>

      {showUndetected && undetected.length > 0 && (
        <div style={{ ...styles.grid, opacity: 0.65 }}>
          {undetected.map((c) => (
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
          type="button"
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
    </>
  );
}
