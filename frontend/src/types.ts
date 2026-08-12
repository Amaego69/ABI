export type RunStatus =
  | 'pending'
  | 'running'
  | 'awaiting_approval'
  | 'done'
  | 'failed'

export type PipelineStage =
  | 'triage'
  | 'repo_fetch'
  | 'locator'
  | 'root_cause'
  | 'fix_generator'
  | 'sandbox_test'
  | 'pr_writer'
  | 'report'

export const PIPELINE_STAGES: { id: PipelineStage; label: string }[] = [
  { id: 'triage', label: 'Triage' },
  { id: 'repo_fetch', label: 'Fetch Repo' },
  { id: 'locator', label: 'Locator' },
  { id: 'root_cause', label: 'Root Cause' },
  { id: 'fix_generator', label: 'Fix Generator' },
  { id: 'sandbox_test', label: 'Sandbox Test' },
  { id: 'pr_writer', label: 'PR Writer' },
  { id: 'report', label: 'Report' },
]

export interface AnalyzeResponse {
  run_id: string
  status: RunStatus
}

export interface AnalyzeStatusResponse {
  run_id: string
  status: RunStatus
  current_stage: string | null
  stages_completed: string[]
  retry_count: number
  max_retries: number
  needs_manual_review: boolean
  error: string | null
  updated_at: string | null
}

export interface FilePatch {
  file_path: string
  original_code: string
  fixed_code: string
}

export interface ClientReport {
  summary: string
  error_type: string | null
  error_message: string | null
  file_path: string | null
  line_number: number | null
  root_cause: string | null
  fix_explanation: string | null
  original_code: string | null
  fixed_code: string | null
  files?: FilePatch[]
  tests_passed: boolean | null
  attempts: number
  pr_url: string | null
  needs_manual_review: boolean
  status_message: string
  pr_title: string | null
  pr_body: string | null
}

export interface PRResult {
  branch_name: string
  pr_url: string | null
  pr_number: number | null
  status: 'created' | 'failed' | 'pending_approval'
}

export interface ProposedFixDiff {
  file_path?: string
  original_code?: string
  fixed_code?: string
  explanation?: string
  files?: FilePatch[]
}

export interface AnalyzeResultResponse {
  run_id: string
  status: RunStatus
  stages_completed: string[]
  state: {
    bug_report?: {
      error_type?: string | null
      error_message?: string | null
      raw_traceback?: string
    }
    code_location?: {
      file_path: string
      function_name?: string | null
      line_number?: number | null
      surrounding_code?: string
    } | null
    root_cause?: {
      hypothesis: string
      confidence: 'low' | 'medium' | 'high'
    } | null
    proposed_fix?: {
      file_path?: string
      original_code?: string
      fixed_code?: string
      explanation: string
      files?: FilePatch[]
    } | null
    test_results?: { passed: boolean; output: string; attempt_number: number }[]
    retry_count?: number
    max_retries?: number
    needs_manual_review?: boolean
    pr_title?: string | null
    pr_body?: string | null
  } | null
  report: ClientReport | null
  pr_result: PRResult | null
  diff: ProposedFixDiff | null
  error: string | null
}

export interface ApproveResponse {
  run_id: string
  status: RunStatus
  pr_result: PRResult | null
  message: string
}
