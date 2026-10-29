'use client'
import { useTranslation } from 'react-i18next'
import Link from 'next/link'
import { useCallback, useEffect, useState } from 'react'
import { apiFetch, apiUrl, readApiResponse } from '@/lib/api'

export type Source = {
  id: string
  kb_name: string
  doc_name: string | null
  page_start: number | null
  text: string
  notebook_id?: string
  provenance: Record<string, unknown>
}
export type Claim = { text: string; source_ids: string[] }
export type Quiz = Claim & { topic: string; options: string[]; answer: number; explanation: string }
export type Artifact = {
  id: string
  kind: string
  title: string
  status?: string
  warning?: string
  sources?: Source[]
  claims?: Claim[]
  pack?: { goals: Claim[]; summary: Claim[]; concepts: Claim[]; quiz: Quiz[]; rubric: Claim[] }
  checks?: { check: string; status: string; seconds: number; detail: unknown }[]
}
export type Job = {
  id: string
  kind: string
  status: string
  progress: number
  created_at: number
  updated_at: number
  error: string | null
  result?: { artifact_id?: string; phase?: string }
  payload: Record<string, unknown>
}
export const button =
  'rounded-lg bg-blue-600 px-4 py-2 text-white disabled:opacity-50 hover:bg-blue-700'
export const input = 'w-full rounded-lg border border-slate-300 bg-white text-slate-900 dark:border-slate-600 dark:bg-slate-800 dark:text-white px-3 py-2'
export const panel = 'rounded-xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800/50 p-5 space-y-4'
export async function request<T>(path: string, body?: unknown): Promise<T> {
  return readApiResponse(
    await apiFetch(
      apiUrl(path),
      body === undefined
        ? undefined
        : {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
          }
    )
  )
}
export function WorkspaceShell({
  title,
  description,
  children,
}: {
  title: string
  description: string
  children: React.ReactNode
}) {
  const { t } = useTranslation()

  return (
    <main className="mx-auto max-w-7xl p-5 md:p-8 space-y-6 text-slate-900 dark:text-slate-100">
      <header>
        <h1 className="text-3xl font-semibold">{title}</h1>
        <p className="mt-2 text-slate-500 dark:text-slate-400">{description}</p>
      </header>
      <nav aria-label={t('Learning workspace')} className="flex flex-wrap gap-4 text-blue-600 dark:text-blue-300">
        {[
          ['/evidence', 'Evidence Workspace'],
          ['/study-packs', 'Study Packs'],
          ['/review', 'Adaptive Review'],
          ['/jobs', 'Job Center'],
          ['/settings/diagnostics', 'Settings Diagnostics'],
        ].map(([href, label]) => (
          <Link key={href} href={href} className="underline underline-offset-4">
            {label}
          </Link>
        ))}
      </nav>
      {children}
    </main>
  )
}
export function ErrorMessage({ error }: { error: string }) {
  return error ? (
    <p role="alert" className="rounded-lg border border-red-700 bg-red-950/40 p-3 text-red-200">
      {error}
    </p>
  ) : null
}
export function useArtifacts(kind: string) {
  const [items, setItems] = useState<{ id: string; title: string }[]>([])
  const [error, setError] = useState('')
  const refresh = useCallback(async () => {
    try {
      const data = await request<{ artifacts: { id: string; title: string }[] }>(
        `/api/v1/learning/artifacts?kind=${kind}`
      )
      setItems(data.artifacts)
      setError('')
    } catch (e) {
      setError(String(e))
    }
  }, [kind])
  useEffect(() => {
    const timer = setTimeout(() => void refresh(), 0)
    return () => clearTimeout(timer)
  }, [refresh])
  return { items, refresh, error }
}
export function useActiveArtifact() {
  const [artifact, setArtifact] = useState<Artifact | null>(null)
  const [error, setError] = useState('')
  const open = useCallback(async (id: string) => {
    try {
      const data = await request<Artifact>(`/api/v1/learning/artifacts/${encodeURIComponent(id)}`)
      setArtifact(data)
      setError('')
      window.history.replaceState(
        null,
        '',
        `${window.location.pathname}?artifact=${encodeURIComponent(id)}`
      )
    } catch (e) {
      setError(String(e))
    }
  }, [])
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get('artifact')
    if (id) {
      const timer = setTimeout(() => void open(id), 0)
      return () => clearTimeout(timer)
    }
  }, [open])
  return { artifact, open, error }
}
export function useDurableJob(key: string, onDone: (id: string) => void) {
  const [id, setId] = useState<string | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    const timer = setTimeout(() => setId(localStorage.getItem(`edunote-job-${key}`)), 0)
    return () => clearTimeout(timer)
  }, [key])
  const track = (value: Job) => {
    setJob(value)
    setId(value.id)
    setError('')
    localStorage.setItem(`edunote-job-${key}`, value.id)
  }
  useEffect(() => {
    if (!id) return
    let stopped = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const state = await request<{ job: Job }>(`/api/v1/jobs/${encodeURIComponent(id)}`)
        if (stopped) return
        setJob(state.job)
        setError('')
        if (['completed', 'failed', 'cancelled'].includes(state.job.status)) {
          localStorage.removeItem(`edunote-job-${key}`)
          if (state.job.result?.artifact_id) onDone(state.job.result.artifact_id)
          return
        }
      } catch (e) {
        if (!stopped) setError(String(e))
      }
      if (!stopped) timer = setTimeout(poll, 2000)
    }
    void poll()
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [id, key, onDone])
  return { job, track, error, busy: !!job && ['queued', 'running'].includes(job.status) }
}
export function JobNotice({ job }: { job: Job | null }) {
  const { t } = useTranslation()
  return job ? (
    <div role="status" className={panel}>
      <Link className="text-blue-600 dark:text-blue-300 underline" href={`/jobs?job=${encodeURIComponent(job.id)}`}>
        {job.id}
      </Link>
      <p>
        {job.status} {t('·')} {job.progress}
        {t('%')} {job.result?.phase ?? ''}
      </p>
      {job.status === 'cancelled' && (
        <p>
          {t(
            'Cancellation requested. The worker stops the local process; a remote provider may continue inference.'
          )}
        </p>
      )}
      {job.error && <ErrorMessage error={job.error} />}
    </div>
  ) : null
}
export function Sources({ sources }: { sources: Source[] }) {
  const { t } = useTranslation()

  const [selected, setSelected] = useState<Source | null>(null)
  return (
    <section className={panel}>
      <h2 className="text-xl font-semibold">{t('Source evidence')}</h2>
      <p className="text-sm text-slate-500 dark:text-slate-400">
        {t(
          'Source IDs refer to saved retrieval snapshots. A citation alone does not verify the generated claim.'
        )}
      </p>
      {sources.map(source => (
        <article
          key={source.id}
          id={source.id}
          className="border-t border-slate-700 pt-3 space-y-2"
        >
          <p className="font-medium">
            {source.doc_name || 'Index excerpt — original document unavailable'} {t('·')}{' '}
            {source.page_start ? `page ${source.page_start}` : 'page unknown'}
          </p>
          <code className="text-xs break-all">{source.id}</code>
          <blockquote className="whitespace-pre-wrap border-l-2 border-blue-500 pl-3 text-sm text-slate-600 dark:text-slate-300">
            {source.text}
          </blockquote>
          <details>
            <summary className="cursor-pointer text-sm text-blue-600 dark:text-blue-300">{t('Provenance')}</summary>
            <pre className="text-xs whitespace-pre-wrap break-all">
              {JSON.stringify(source.provenance, null, 2)}
            </pre>
          </details>
          {source.kb_name && source.doc_name && (
            <button className={button} onClick={() => setSelected(source)}>
              {t('Open original document')}
            </button>
          )}
        </article>
      ))}
      {selected && (
        <div className="space-y-3">
          <button className={button} onClick={() => setSelected(null)}>
            {t('Close document')}
          </button>
          <a
            className="ml-4 underline text-blue-600 dark:text-blue-300"
            target="_blank"
            rel="noreferrer"
            href={
              apiUrl(`/api/v1/learning/sources/${encodeURIComponent(selected.id)}/document`) +
              `#page=${selected.page_start || 1}`
            }
          >
            {t('Open in new tab')}
          </a>
          <iframe
            title={`Original source ${selected.doc_name}`}
            className="w-full h-[65vh] rounded-lg bg-white"
            src={
              apiUrl(`/api/v1/learning/sources/${encodeURIComponent(selected.id)}/document`) +
              `#page=${selected.page_start || 1}`
            }
          />
        </div>
      )}
    </section>
  )
}
export function Claims({ items }: { items: Claim[] }) {
  const { t } = useTranslation()
  return (
    <ul className="space-y-4">
      {items.map((item, index) => (
        <li key={index} className="whitespace-pre-wrap">
          {item.text}
          <div className="flex flex-wrap gap-2 mt-2">
            {item.source_ids.map(id => (
              <a key={id} className="text-xs text-blue-600 dark:text-blue-300 underline" href={`#${id}`}>
                {id}
              </a>
            ))}
          </div>
        </li>
      ))}
    </ul>
  )
}
export function ExportLinks({ id }: { id: string }) {
  const { t } = useTranslation()
  return (
    <div className="flex gap-5 text-blue-600 dark:text-blue-300">
      {['json', 'markdown', 'text'].map(format => (
        <a
          key={format}
          className="underline"
          href={apiUrl(
            `/api/v1/learning/artifacts/${encodeURIComponent(id)}/export?format=${format}`
          )}
        >
          {t('Download')} {format}
        </a>
      ))}
    </div>
  )
}
