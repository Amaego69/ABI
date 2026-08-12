import type {
  AnalyzeResponse,
  AnalyzeResultResponse,
  AnalyzeStatusResponse,
  ApproveResponse,
} from './types'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })

  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      detail = body.detail ?? JSON.stringify(body)
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }

  return response.json() as Promise<T>
}

export function startAnalyze(traceback: string): Promise<AnalyzeResponse> {
  return request<AnalyzeResponse>('/api/analyze', {
    method: 'POST',
    body: JSON.stringify({ traceback }),
  })
}

export function getStatus(runId: string): Promise<AnalyzeStatusResponse> {
  return request<AnalyzeStatusResponse>(`/api/analyze/${runId}/status`)
}

export function getResult(runId: string): Promise<AnalyzeResultResponse> {
  return request<AnalyzeResultResponse>(`/api/analyze/${runId}/result`)
}

export function approvePr(runId: string): Promise<ApproveResponse> {
  return request<ApproveResponse>(`/api/analyze/${runId}/approve`, {
    method: 'POST',
  })
}
