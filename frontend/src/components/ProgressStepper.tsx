import { PIPELINE_STAGES, type AnalyzeStatusResponse, type PipelineStage } from '../types'

function stageState(
  stageId: PipelineStage,
  status: AnalyzeStatusResponse,
): 'done' | 'active' | 'pending' {
  const order = PIPELINE_STAGES.map((s) => s.id)
  const thisIdx = order.indexOf(stageId)
  const completed = status.stages_completed
  const current = status.current_stage as PipelineStage | null

  if (status.status === 'awaiting_approval' || status.status === 'done') {
    return 'done'
  }

  if (status.status === 'failed') {
    if (completed.includes(stageId)) return 'done'
    if (current === stageId) return 'active'
    const currentIdx = current ? order.indexOf(current) : -1
    if (currentIdx > thisIdx) return 'done'
    return 'pending'
  }

  if (completed.includes(stageId) && current !== stageId) {
    return 'done'
  }
  if (current === stageId) {
    return 'active'
  }

  const currentIdx = current ? order.indexOf(current) : -1
  if (currentIdx > thisIdx) return 'done'

  return 'pending'
}

interface Props {
  status: AnalyzeStatusResponse
}

export function ProgressStepper({ status }: Props) {
  return (
    <ol className="stepper">
      {PIPELINE_STAGES.map((stage, index) => {
        const state = stageState(stage.id, status)
        const isSandbox = stage.id === 'sandbox_test'

        return (
          <li key={stage.id} className={`step ${state}`}>
            <div className="step-rail">
              <div className="step-dot" />
              {index < PIPELINE_STAGES.length - 1 && <div className="step-line" />}
            </div>
            <div className="step-body">
              <div className="step-title">{stage.label}</div>
              {state === 'active' && <div className="step-sub">Running…</div>}
              {state === 'done' && <div className="step-sub">Complete</div>}
              {isSandbox && status.retry_count > 0 && (
                <div className="step-sub">
                  Retry {status.retry_count}/{status.max_retries}
                </div>
              )}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
