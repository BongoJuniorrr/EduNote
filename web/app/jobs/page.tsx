'use client'
import { useTranslation } from 'react-i18next'
import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import {
  ErrorMessage,
  Job,
  WorkspaceShell,
  button,
  input,
  panel,
  request,
} from '@/components/learning/shared'
export default function JobsPage() {
  const { t } = useTranslation()

  const [jobs, setJobs] = useState<Job[]>([])
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const refresh = useCallback(async () => {
    try {
      const data = await request<{ jobs: Job[] }>('/api/v1/jobs')
      setJobs(data.jobs)
      setError('')
    } catch (e) {
      setError(String(e))
    }
  }, [])
  useEffect(() => {
    void refresh()
    const timer = setInterval(() => void refresh(), 3000)
    return () => clearInterval(timer)
  }, [refresh])
  async function action(job: Job, action: string) {
    setBusy(job.id)
    try {
      await request(`/api/v1/jobs/${encodeURIComponent(job.id)}/${action}`, {})
      await refresh()
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(null)
    }
  }
  const artifactRoute = (kind: string) =>
    kind === 'evidence'
      ? '/evidence'
      : kind === 'study_pack'
        ? '/study-packs'
        : '/settings/diagnostics'
  return (
    <WorkspaceShell
      title={t('Job Center')}
      description={t(
        'Track durable parser, evidence, study and diagnostic jobs. Refreshing the browser does not cancel work.'
      )}
    >
      <ErrorMessage error={error} />
      <section className={panel}>
        <label>
          {t('Status filter')}
          <select className={input} value={filter} onChange={e => setFilter(e.target.value)}>
            {['', 'queued', 'running', 'completed', 'failed', 'cancelled'].map(value => (
              <option key={value} value={value}>
                {value || 'All statuses'}
              </option>
            ))}
          </select>
        </label>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          {t(
            'Latest 100 jobs. Cancelling stops the local worker process and its children. Already-sent remote inference requests may continue at the provider. Legacy interactive chat/solver sessions are not durable jobs.'
          )}
        </p>
      </section>
      {jobs
        .filter(job => !filter || job.status === filter)
        .map(job => (
          <article key={job.id} id={job.id} className={panel}>
            <div className="flex justify-between flex-wrap gap-3">
              <h2 className="text-xl">{job.kind}</h2>
              <span>{job.status}</span>
            </div>
            <p className="font-mono text-xs break-all">{job.id}</p>
            <p>
              {new Date(job.created_at * 1000).toLocaleString()} {t('· last update')}{' '}
              {new Date(job.updated_at * 1000).toLocaleTimeString()}
            </p>
            <progress
              aria-label={`${job.kind} progress`}
              max={100}
              value={job.progress}
              className="w-full"
            />
            <p>
              {job.progress}
              {t('%')} {job.result?.phase || ''}
            </p>
            {job.error && <ErrorMessage error={job.error} />}
            <div className="flex flex-wrap gap-3">
              {['queued', 'running'].includes(job.status) && (
                <button
                  className={button}
                  disabled={busy === job.id}
                  onClick={() => void action(job, 'cancel')}
                >
                  {t('Cancel job')}
                </button>
              )}
              {['failed', 'cancelled'].includes(job.status) &&
                ['evidence', 'study_pack', 'settings_diagnostics'].includes(job.kind) && (
                  <button
                    className={button}
                    disabled={busy === job.id}
                    onClick={() => void action(job, 'retry')}
                  >
                    {t('Retry with current settings')}
                  </button>
                )}
              {job.result?.artifact_id && (
                <Link
                  href={`${artifactRoute(job.kind)}?artifact=${encodeURIComponent(job.result.artifact_id)}`}
                  className="text-blue-600 dark:text-blue-300 underline"
                >
                  {t('Open result')}
                </Link>
              )}
              {job.kind === 'document_preview' && job.status === 'completed' && (
                <details className="w-full">
                  <summary className="cursor-pointer text-blue-600 dark:text-blue-300">
                    {t('Extraction result')}
                  </summary>
                  <pre className="text-sm whitespace-pre-wrap break-all max-h-96 overflow-auto">
                    {JSON.stringify(job.result, null, 2)}
                  </pre>
                </details>
              )}
            </div>
          </article>
        ))}
      {!jobs.length && <p>{t('No durable jobs yet.')}</p>}
    </WorkspaceShell>
  )
}
