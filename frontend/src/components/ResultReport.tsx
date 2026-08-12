import ReactDiffViewer, { DiffMethod } from 'react-diff-viewer-continued'
import type { AnalyzeResultResponse, FilePatch } from '../types'

interface Props {
  result: AnalyzeResultResponse
  approving: boolean
  approveError: string | null
  onApprove: () => void
  onReset: () => void
}

function collectPatches(result: AnalyzeResultResponse): FilePatch[] {
  const fromDiff = result.diff?.files
  if (fromDiff && fromDiff.length > 0) return fromDiff

  const fromReport = result.report?.files
  if (fromReport && fromReport.length > 0) return fromReport

  const fromState = result.state?.proposed_fix?.files
  if (fromState && fromState.length > 0) return fromState

  const legacy =
    result.diff ??
    result.state?.proposed_fix ??
    (result.report?.original_code || result.report?.fixed_code
      ? {
          file_path: result.report?.file_path ?? undefined,
          original_code: result.report?.original_code ?? undefined,
          fixed_code: result.report?.fixed_code ?? undefined,
        }
      : null)

  if (legacy && (legacy.original_code || legacy.fixed_code)) {
    return [
      {
        file_path: legacy.file_path ?? 'unknown',
        original_code: legacy.original_code ?? '',
        fixed_code: legacy.fixed_code ?? '',
      },
    ]
  }
  return []
}

const DIFF_STYLES = {
  variables: {
    dark: {
      diffViewerBackground: '#0a0a0b',
      diffViewerColor: '#ececee',
      addedBackground: 'rgba(62, 207, 142, 0.15)',
      removedBackground: 'rgba(242, 85, 90, 0.15)',
      wordAddedBackground: 'rgba(62, 207, 142, 0.28)',
      wordRemovedBackground: 'rgba(242, 85, 90, 0.28)',
      addedGutterBackground: 'rgba(62, 207, 142, 0.2)',
      removedGutterBackground: 'rgba(242, 85, 90, 0.2)',
      gutterBackground: '#111113',
      gutterBackgroundDark: '#0a0a0b',
      highlightBackground: 'rgba(110, 168, 254, 0.15)',
      highlightGutterBackground: 'rgba(110, 168, 254, 0.2)',
      codeFoldGutterBackground: '#161618',
      codeFoldBackground: '#161618',
      emptyLineBackground: '#111113',
    },
  },
  contentText: {
    fontFamily: 'IBM Plex Mono, ui-monospace, monospace',
    fontSize: 12,
  },
}

export function ResultReport({
  result,
  approving,
  approveError,
  onApprove,
  onReset,
}: Props) {
  const report = result.report
  const location = result.state?.code_location
  const rootCause = report?.root_cause ?? result.state?.root_cause?.hypothesis
  const testsPassed = report?.tests_passed
  const attempts = report?.attempts ?? result.state?.retry_count ?? 0
  const needsReview =
    Boolean(report?.needs_manual_review) ||
    (result.status === 'done' && testsPassed === false)
  const prUrl = result.pr_result?.pr_url ?? report?.pr_url
  const canApprove =
    result.status === 'awaiting_approval' &&
    result.pr_result?.status === 'pending_approval'

  const patches = collectPatches(result)
  const explanation =
    result.diff?.explanation ??
    result.state?.proposed_fix?.explanation ??
    report?.fix_explanation

  const fileLabel =
    report?.file_path ??
    location?.file_path ??
    patches[0]?.file_path ??
    'unknown'
  const lineLabel = report?.line_number ?? location?.line_number

  return (
    <div className="result-grid">
      <div className="section" style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <h2 style={{ marginBottom: 8 }}>Investigation result</h2>
          <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>
            Run <code style={{ fontFamily: 'var(--mono)' }}>{result.run_id.slice(0, 8)}</code>
            {' · '}
            status <strong>{result.status}</strong>
          </p>
        </div>
        <button type="button" className="btn btn-secondary" onClick={onReset}>
          New analysis
        </button>
      </div>

      {needsReview && (
        <div className="warning-banner">
          ⚠️ Не удалось автоматически подтвердить фикс, требуется ручная проверка. Ниже —
          предложенный diff.
        </div>
      )}

      {result.status === 'awaiting_approval' && (
        <div className="success-banner">
          Fix verified in sandbox. Review the diff, then create the pull request.
        </div>
      )}

      {prUrl && (
        <div className="success-banner">
          Pull request created.{' '}
          <a href={prUrl} target="_blank" rel="noreferrer">
            Open in GitHub
          </a>
        </div>
      )}

      {result.error && <div className="error-banner">{result.error}</div>}

      <section className="section">
        <h2>Location</h2>
        <div className="kv">
          <div className="kv-row">
            <span>File</span>
            <code>{fileLabel}{lineLabel != null ? `:${lineLabel}` : ''}</code>
          </div>
          <div className="kv-row">
            <span>Error</span>
            <code>
              {report?.error_type ?? result.state?.bug_report?.error_type ?? '—'}
              {(report?.error_message || result.state?.bug_report?.error_message) &&
                `: ${report?.error_message ?? result.state?.bug_report?.error_message}`}
            </code>
          </div>
          {location?.function_name && (
            <div className="kv-row">
              <span>Function</span>
              <code>{location.function_name}</code>
            </div>
          )}
          {patches.length > 1 && (
            <div className="kv-row">
              <span>Files in fix</span>
              <code>{patches.map((p) => p.file_path).join(', ')}</code>
            </div>
          )}
        </div>
      </section>

      <section className="section">
        <h2>Root cause</h2>
        <p>{rootCause ?? report?.status_message ?? 'No hypothesis available.'}</p>
        {result.state?.root_cause?.confidence && (
          <p style={{ marginTop: 10, color: 'var(--text-muted)', fontSize: 13 }}>
            Confidence: {result.state.root_cause.confidence}
          </p>
        )}
      </section>

      <section className="section">
        <h2>Sandbox tests</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          {testsPassed === true && <span className="status-pill ok">Passed</span>}
          {testsPassed === false && <span className="status-pill bad">Failed</span>}
          {testsPassed == null && <span className="status-pill wait">Unknown</span>}
          <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>
            Attempts: {attempts}
          </span>
        </div>
        {explanation && (
          <p style={{ marginTop: 12, color: 'var(--text-muted)' }}>{explanation}</p>
        )}
      </section>

      {patches.map((patch) => (
        <section className="section" key={patch.file_path}>
          <h2>Diff — {patch.file_path}</h2>
          <div className="diff-wrap">
            <ReactDiffViewer
              oldValue={patch.original_code}
              newValue={patch.fixed_code}
              splitView
              useDarkTheme
              compareMethod={DiffMethod.LINES}
              leftTitle="Before"
              rightTitle="After"
              styles={DIFF_STYLES}
            />
          </div>
        </section>
      ))}

      <section className="section">
        <h2>Pull request</h2>
        {(report?.pr_title || result.state?.pr_title) && (
          <p style={{ marginBottom: 8, fontWeight: 500 }}>
            {report?.pr_title ?? result.state?.pr_title}
          </p>
        )}
        {(report?.pr_body || result.state?.pr_body) && (
          <pre
            style={{
              margin: '0 0 14px',
              whiteSpace: 'pre-wrap',
              fontFamily: 'var(--mono)',
              fontSize: 12,
              color: 'var(--text-muted)',
              maxHeight: 220,
              overflow: 'auto',
            }}
          >
            {report?.pr_body ?? result.state?.pr_body}
          </pre>
        )}
        <div className="pr-actions">
          {canApprove && (
            <button
              type="button"
              className="btn btn-success"
              onClick={onApprove}
              disabled={approving}
            >
              {approving ? 'Creating PR…' : 'Create Pull Request'}
            </button>
          )}
          {prUrl && (
            <a className="btn btn-secondary" href={prUrl} target="_blank" rel="noreferrer">
              Open in GitHub
            </a>
          )}
          {!canApprove && !prUrl && (
            <p className="hint">
              {needsReview
                ? 'PR was not created because sandbox verification failed.'
                : 'No PR available for this run.'}
            </p>
          )}
        </div>
        {approveError && <div className="error-banner">{approveError}</div>}
      </section>
    </div>
  )
}
