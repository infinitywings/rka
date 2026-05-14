import { ClientSummary, VerifyResult } from "../types";
import { styles } from "../styles";

interface ClientRowProps {
  client: ClientSummary;
  checked: boolean;
  onToggle: () => void;
  verify?: VerifyResult;
  trailing?: React.ReactNode;
}

export function ClientRow({
  client,
  checked,
  onToggle,
  verify,
  trailing,
}: ClientRowProps) {
  return (
    <label style={styles.row}>
      <input type="checkbox" checked={checked} onChange={onToggle} />
      <div style={styles.rowBody}>
        <div style={styles.rowName}>
          {client.display_name}
          <span style={styles.formatTag}>{client.format}</span>
          {client.detection.detected && (
            <span style={styles.detected}> detected</span>
          )}
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
            {verify.reason && (
              <span style={styles.muted}>{verify.reason}</span>
            )}
          </div>
        )}
        {trailing}
      </div>
    </label>
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
