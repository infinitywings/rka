import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

import { styles } from "../styles";
import { ClientSummary, RemoveResult, VerifyResult } from "../types";

interface Props {
  clients: ClientSummary[];
  refreshClients: () => Promise<void>;
}

type ToggleState = "on" | "off" | "pending";

export function SettingsTab({ clients, refreshClients }: Props) {
  const [verify, setVerify] = useState<Record<string, VerifyResult>>({});
  const [toggleState, setToggleState] = useState<Record<string, ToggleState>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [globalMessage, setGlobalMessage] = useState<string>("");

  const refreshVerify = useCallback(async () => {
    const ids = clients.map((c) => c.id);
    const pairs = await invoke<[string, VerifyResult][]>(
      "verify_all_mcp_clients",
      { ids },
    );
    const map = Object.fromEntries(pairs);
    setVerify(map);
    const states: Record<string, ToggleState> = {};
    for (const id of ids) {
      states[id] = map[id]?.rka_entry_present ? "on" : "off";
    }
    setToggleState(states);
  }, [clients]);

  useEffect(() => {
    refreshVerify().catch(() => {});
  }, [refreshVerify]);

  const handleToggle = useCallback(
    async (id: string) => {
      const current = toggleState[id];
      if (current === "pending") return;
      setBusyId(id);
      setToggleState((s) => ({ ...s, [id]: "pending" }));
      try {
        if (current === "on") {
          await invoke<RemoveResult>("remove_mcp_client", { id });
        } else {
          await invoke("merge_mcp_client", { id });
          await invoke<string>("rewrite_launcher").catch(() => "");
        }
        await refreshVerify();
      } catch (e) {
        setGlobalMessage(`Toggle failed (${id}): ${e}`);
        setToggleState((s) => ({
          ...s,
          [id]: current === "on" ? "on" : "off",
        }));
      } finally {
        setBusyId(null);
      }
    },
    [toggleState, refreshVerify],
  );

  const handleShowInFinder = useCallback(async (path: string | null) => {
    if (!path) return;
    try {
      await invoke("show_path_in_finder", { path });
    } catch (e) {
      setGlobalMessage(`Cannot open in Finder: ${e}`);
    }
  }, []);

  const handleReRegister = useCallback(async () => {
    setGlobalMessage("Re-registering…");
    try {
      await invoke<string>("rewrite_launcher");
      const enabled = clients
        .filter((c) => toggleState[c.id] === "on")
        .map((c) => c.id);
      if (enabled.length > 0) {
        await invoke("merge_mcp_clients", { ids: enabled });
      }
      await refreshClients();
      await refreshVerify();
      setGlobalMessage(`Re-registered ${enabled.length} client(s) ✓`);
    } catch (e) {
      setGlobalMessage(`Re-register failed: ${e}`);
    }
  }, [clients, toggleState, refreshClients, refreshVerify]);

  const handleShowAllConfigs = useCallback(async () => {
    const enabledPaths = clients
      .filter(
        (c) => toggleState[c.id] === "on" && c.config_path,
      )
      .map((c) => c.config_path!) as string[];
    if (enabledPaths.length === 0) {
      setGlobalMessage("No enabled clients with config files yet.");
      return;
    }
    for (const p of enabledPaths) {
      await invoke("show_path_in_finder", { path: p }).catch(() => {});
    }
  }, [clients, toggleState]);

  const handleVerifyAll = useCallback(async () => {
    setGlobalMessage("Verifying all…");
    await refreshVerify();
    setGlobalMessage("Verification complete.");
  }, [refreshVerify]);

  return (
    <section style={styles.panel}>
      <h2 style={styles.panelTitle}>MCP client settings</h2>
      <p style={styles.muted}>
        Toggle RKA's MCP registration per client. Removing a client preserves
        every other server in its config; an automatic timestamped backup is
        written before each change.
      </p>

      <div style={styles.globalActions}>
        <button style={styles.secondaryBtn} onClick={handleReRegister}>
          Re-register MCP
        </button>
        <button style={styles.secondaryBtn} onClick={handleShowAllConfigs}>
          Show all MCP config files
        </button>
        <button style={styles.secondaryBtn} onClick={handleVerifyAll}>
          Verify all
        </button>
      </div>
      {globalMessage && <div style={styles.muted}>{globalMessage}</div>}

      <h3 style={styles.panelSubtitle}>Per-client</h3>
      <div style={styles.grid}>
        {clients.map((c) => {
          const state = toggleState[c.id] ?? "off";
          const v = verify[c.id];
          const isOn = state === "on";
          const isPending = state === "pending" || busyId === c.id;
          return (
            <div key={c.id} style={styles.row}>
              <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <input
                  type="checkbox"
                  checked={isOn}
                  disabled={isPending}
                  onChange={() => handleToggle(c.id)}
                />
              </label>
              <div style={styles.rowBody}>
                <div style={styles.rowName}>
                  {c.display_name}
                  <span style={styles.formatTag}>{c.format}</span>
                  {c.detection.detected && (
                    <span style={styles.detected}>detected</span>
                  )}
                  {!c.detection.detected && (
                    <span style={{ ...styles.muted, marginLeft: 6 }}>
                      (not installed)
                    </span>
                  )}
                </div>
                {c.config_path && (
                  <div style={styles.rowPath}>{c.config_path}</div>
                )}
                {v && (
                  <div style={styles.verifyRow}>
                    <Pill ok={v.config_syntax_ok} label="config" />
                    <Pill ok={v.rka_entry_present} label="rka entry" />
                    <Pill ok={v.backend_reachable} label="backend" />
                    <Pill ok={v.capabilities_reachable} label="capabilities" />
                    {v.reason && <span style={styles.muted}>{v.reason}</span>}
                  </div>
                )}
                <div style={styles.perClientActions}>
                  <button
                    style={styles.smallBtn}
                    onClick={() => handleShowInFinder(c.config_path)}
                    disabled={!c.config_path}
                  >
                    Show in Finder
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function Pill({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      style={{
        ...styles.pill,
        background: ok ? "#e6f4ea" : "#fdecea",
        color: ok ? "#137333" : "#a50e0e",
      }}
    >
      {ok ? "✓" : "✗"} {label}
    </span>
  );
}
