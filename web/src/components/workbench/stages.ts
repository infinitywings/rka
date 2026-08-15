import {
  BookOpenText,
  Box,
  CircleHelp,
  FlaskConical,
  Focus,
  GitPullRequestArrow,
  Lightbulb,
  ListTree,
  Map,
  ScanSearch,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"

export type WorkbenchStageId =
  | "seed"
  | "spine"
  | "scope"
  | "landscape"
  | "gap"
  | "response"
  | "rqs"
  | "contributions"
  | "evaluation"
  | "outline"

export type StageVerdict = "Ready" | "Needs review" | "Blocked" | "Exploratory"

export interface WorkbenchStage {
  id: WorkbenchStageId
  label: string
  question: string
  icon: LucideIcon
}

export const WORKBENCH_STAGES: WorkbenchStage[] = [
  { id: "seed", label: "Seed insight", question: "What is the smallest non-obvious idea?", icon: Lightbulb },
  { id: "spine", label: "Paper spine", question: "Can the argument be read as one paragraph?", icon: GitPullRequestArrow },
  { id: "scope", label: "Problem and scope", question: "What exactly is in and out of scope?", icon: Focus },
  { id: "landscape", label: "Literature and SOTA", question: "What exists and on which comparison axes?", icon: Map },
  { id: "gap", label: "Gap and motivation", question: "Which gap is real, material, and supported?", icon: ScanSearch },
  { id: "response", label: "Insight and response", question: "How does the mechanism address the gap?", icon: Box },
  { id: "rqs", label: "Research questions", question: "What questions organize the evidence?", icon: CircleHelp },
  { id: "contributions", label: "Contributions", question: "What bounded claims will the paper defend?", icon: BookOpenText },
  { id: "evaluation", label: "Evaluation contract", question: "What evidence would make each claim credible?", icon: FlaskConical },
  { id: "outline", label: "Outline", question: "What sequence makes the promise easy to verify?", icon: ListTree },
]
