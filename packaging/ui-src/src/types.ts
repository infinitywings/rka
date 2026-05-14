export interface SidecarStatus {
  running: boolean;
  pid: number | null;
  consecutive_failures: number;
}

export interface ProbeResult {
  detected: boolean;
  evidence: string[];
}

export interface ClientSummary {
  id: string;
  display_name: string;
  format: "json" | "toml";
  detection: ProbeResult;
  config_path: string | null;
}

export interface MergeResult {
  config_path: string;
  backup_path: string | null;
  previous_rka_command: string | null;
  new_rka_command: string;
}

export interface RemoveResult {
  config_path: string;
  removed: boolean;
  backup_path: string | null;
}

export interface VerifyResult {
  config_syntax_ok: boolean;
  rka_entry_present: boolean;
  backend_reachable: boolean;
  capabilities_reachable: boolean;
  reason: string | null;
}

export interface MergeSummary {
  client_id: string;
  result: MergeResult | null;
  error: string | null;
}
