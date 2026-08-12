interface Props {
  traceback: string
  onChange: (value: string) => void
  onAnalyze: () => void
  loading: boolean
  error: string | null
}

const README_URL =
  import.meta.env.VITE_BUGGY_APP_README_URL ??
  'https://github.com/search?q=buggy-app&type=repositories'

export function Dashboard({ traceback, onChange, onAnalyze, loading, error }: Props) {
  return (
    <section className="panel">
      <h1>Investigate a crash</h1>
      <p className="lead">
        Paste a Python traceback. The multi-agent pipeline will locate the fault, propose a
        fix, verify it in a sandbox, and prepare a pull request.
      </p>

      <label className="label" htmlFor="traceback">
        Traceback
      </label>
      <textarea
        id="traceback"
        className="traceback-input"
        value={traceback}
        onChange={(e) => onChange(e.target.value)}
        placeholder={`Traceback (most recent call last):\n  File "utils.py", line 18, in find_cheapest_item\n    cheapest = items[0]\nIndexError: list index out of range`}
        spellCheck={false}
      />

      <div className="actions">
        <button
          type="button"
          className="btn btn-primary"
          onClick={onAnalyze}
          disabled={loading || !traceback.trim()}
        >
          {loading ? 'Starting…' : 'Analyze this error'}
        </button>
        <p className="hint">
          Нет traceback под рукой? Запустите тестовое приложение{' '}
          <a href={README_URL} target="_blank" rel="noreferrer">
            buggy-app — инструкция
          </a>
        </p>
      </div>

      {error && <div className="error-banner">{error}</div>}
    </section>
  )
}
