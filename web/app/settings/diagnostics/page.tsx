'use client'
import { useTranslation } from 'react-i18next'
import { useCallback, useState } from 'react'
import {
  ErrorMessage,
  Job,
  JobNotice,
  WorkspaceShell,
  button,
  input,
  panel,
  request,
  useActiveArtifact,
  useArtifacts,
  useDurableJob,
} from '@/components/learning/shared'
const checks = [
  ['runtime', 'Runtime and parser packages'],
  ['text', 'Text completion'],
  ['multiturn', 'Multiple conversation turns'],
  ['json', 'Structured JSON'],
  ['vision', 'Image reading (vision)'],
  ['embedding', 'Embedding dimensions and finite vectors'],
  ['parser', 'Selected parser: real PDF extraction'],
  ['presenton', 'Presenton availability'],
]
export default function DiagnosticsPage() {
  const { t } = useTranslation()

  const [selected, setSelected] = useState(['runtime', 'text', 'multiturn', 'json', 'embedding'])
  const [error, setError] = useState('')
  const [sending, setSending] = useState(false)
  const { artifact, open, error: openError } = useActiveArtifact()
  const { items, refresh, error: listError } = useArtifacts('settings_diagnostics')
  const done = useCallback(
    (id: string) => {
      void open(id)
      void refresh()
    },
    [open, refresh]
  )
  const job = useDurableJob('diagnostics', done)
  async function run() {
    setSending(true)
    setError('')
    try {
      const value = await request<{ job: Job }>('/api/v1/learning/diagnostics', {
        checks: selected,
        request_id: crypto.randomUUID(),
      })
      job.track(value.job)
    } catch (e) {
      setError(String(e))
    } finally {
      setSending(false)
    }
  }
  const current = artifact?.kind === 'settings_diagnostics' ? artifact : null
  return (
    <WorkspaceShell
      title={t('Settings Diagnostics')}
      description={t(
        'Separate checks for text, conversation, JSON, vision, embeddings, parsing and Presenton. Tests use the active saved settings.'
      )}
    >
      <ErrorMessage error={error || job.error || openError || listError} />
      <section className={panel}>
        <fieldset className="grid md:grid-cols-2 gap-4">
          <legend className="mb-4">{t('Choose checks')}</legend>
          {checks.map(([id, label]) => (
            <label key={id} className="flex gap-3">
              <input
                type="checkbox"
                checked={selected.includes(id)}
                onChange={e =>
                  setSelected(previous =>
                    e.target.checked ? [...previous, id] : previous.filter(value => value !== id)
                  )
                }
              />
              {label}
            </label>
          ))}
        </fieldset>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          {t(
            'LLM checks allow up to 300 seconds each and run sequentially. Parser checks can download models on first use. Vision sends a generated test image to the configured provider. A text pass does not imply OCR or RAG quality.'
          )}
        </p>
        <button
          className={button}
          disabled={sending || job.busy || !selected.length}
          onClick={() => void run()}
        >
          {t('Run selected diagnostics')}
        </button>
      </section>
      <JobNotice job={job.job} />
      <label>
        {t('Saved diagnostics')}
        <select
          className={input}
          value={current?.id || ''}
          onChange={e => {
            if (e.target.value) void open(e.target.value)
          }}
        >
          <option value="">{t('Select diagnostics')}</option>
          {items.map(value => (
            <option key={value.id} value={value.id}>
              {value.title} {t('·')} {value.id}
            </option>
          ))}
        </select>
      </label>
      {current && (
        <section className={panel}>
          <h2 className="text-xl">{t('Results')}</h2>
          {current.checks?.map(check => (
            <article key={check.check} className="border-t border-slate-700 pt-3">
              <h3 className={check.status === 'passed' ? 'text-green-300' : 'text-red-300'}>
                {check.check} {t('·')} {check.status} {t('·')} {check.seconds}
                {t('s')}
              </h3>
              <pre className="text-sm whitespace-pre-wrap break-all mt-2">
                {typeof check.detail === 'string'
                  ? check.detail
                  : JSON.stringify(check.detail, null, 2)}
              </pre>
            </article>
          ))}
        </section>
      )}
    </WorkspaceShell>
  )
}
