import { useCallback, useEffect, useState } from 'react'
import { approvePr, getResult, getStatus, startAnalyze } from './api'
import { Dashboard } from './components/Dashboard'
import { ProgressStepper } from './components/ProgressStepper'
import { ResultReport } from './components/ResultReport'
import type { AnalyzeResultResponse, AnalyzeStatusResponse, RunStatus } from './types'

type View = 'home' | 'progress' | 'result'

const TERMINAL: RunStatus[] = ['awaiting_approval', 'done', 'failed']

export default function App() {
  const [view, setView] = useState<View>('home')
  const [traceback, setTraceback] = useState('')
  const [runId, setRunId] = useState<string | null>(null)
  const [status, setStatus] = useState<AnalyzeStatusResponse | null>(null)
  const [result, setResult] = useState<AnalyzeResultResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [approving, setApproving] = useState(false)
  const [approveError, setApproveError] = useState<string | null>(null)

  const reset = () => {
    setView('home')
    setRunId(null)
    setStatus(null)
    setResult(null)
    setError(null)
    setApproveError(null)
    setStarting(false)
    setApproving(false)
  }

  const handleAnalyze = async () => {
    setError(null)
    setStarting(true)
    try {
      const res = await startAnalyze(traceback)
      setRunId(res.run_id)
      setStatus({
        run_id: res.run_id,
        status: res.status,
        current_stage: null,
        stages_completed: [],
        retry_count: 0,
        max_retries: 3,
        needs_manual_review: false,
        error: null,
        updated_at: null,
      })
      setView('progress')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setStarting(false)
    }
  }

  const loadResult = useCallback(async (id: string) => {
    const res = await getResult(id)
    setResult(res)
    setView('result')
  }, [])

  useEffect(() => {
    if (!runId || view !== 'progress') return

    let cancelled = false
    let timer: number | undefined

    const poll = async () => {
      try {
        const next = await getStatus(runId)
        if (cancelled) return
        setStatus(next)

        if (TERMINAL.includes(next.status)) {
          await loadResult(runId)
          return
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err))
        }
      }
      if (!cancelled) {
        timer = window.setTimeout(poll, 1200)
      }
    }

    void poll()
    return () => {
      cancelled = true
      if (timer) window.clearTimeout(timer)
    }
  }, [runId, view, loadResult])

  const handleApprove = async () => {
    if (!runId) return
    setApproveError(null)
    setApproving(true)
    try {
      await approvePr(runId)
      await loadResult(runId)
    } catch (err) {
      setApproveError(err instanceof Error ? err.message : String(err))
    } finally {
      setApproving(false)
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-name">Bug Investigator</div>
          <div className="brand-sub">Automated fix pipeline</div>
        </div>
        <div className="badge">
          <span className="badge-dot" />
          LangGraph · Claude
        </div>
      </header>

      {view === 'home' && (
        <Dashboard
          traceback={traceback}
          onChange={setTraceback}
          onAnalyze={handleAnalyze}
          loading={starting}
          error={error}
        />
      )}

      {view === 'progress' && status && (
        <section className="panel">
          <div className="progress-header">
            <div>
              <h1>Analyzing</h1>
              <div className="meta">run {status.run_id.slice(0, 12)}…</div>
            </div>
            <span className="status-pill wait">{status.status}</span>
          </div>
          <ProgressStepper status={status} />
          {status.error && <div className="error-banner">{status.error}</div>}
          {error && <div className="error-banner">{error}</div>}
        </section>
      )}

      {view === 'result' && result && (
        <ResultReport
          result={result}
          approving={approving}
          approveError={approveError}
          onApprove={handleApprove}
          onReset={reset}
        />
      )}
    </div>
  )
}
