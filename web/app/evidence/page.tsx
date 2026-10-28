'use client'
import { useTranslation } from 'react-i18next'
import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import {
  Artifact,
  Claims,
  ErrorMessage,
  ExportLinks,
  Job,
  JobNotice,
  Sources,
  WorkspaceShell,
  button,
  input,
  panel,
  request,
  useActiveArtifact,
  useArtifacts,
  useDurableJob,
} from '@/components/learning/shared'

export default function EvidencePage() {
  const { t } = useTranslation()

  const [topic, setTopic] = useState('')
  const [kb, setKb] = useState('')
  const [notebook, setNotebook] = useState('')
  const [kbs, setKbs] = useState<{ name: string }[]>([])
  const [notebooks, setNotebooks] = useState<{ id: string; name: string }[]>([])
  const [error, setError] = useState('')
  const [sending, setSending] = useState(false)
  const { items, refresh, error: listError } = useArtifacts('evidence')
  const { artifact, open, error: openError } = useActiveArtifact()
  const done = useCallback(
    (id: string) => {
      void open(id)
      void refresh()
    },
    [open, refresh]
  )
  const job = useDurableJob('evidence', done)
  useEffect(() => {
    Promise.all([
      request<{ name: string }[]>('/api/v1/knowledge/list'),
      request<{ notebooks: { id: string; name: string }[] }>('/api/v1/notebook/list'),
    ])
      .then(([a, b]) => {
        setKbs(a)
        setNotebooks(b.notebooks)
      })
      .catch(e => setError(String(e)))
  }, [])
  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setSending(true)
    setError('')
    try {
      const data = await request<{ job: Job }>('/api/v1/learning/evidence', {
        topic,
        kb_name: kb || null,
        notebook_id: notebook || null,
        request_id: crypto.randomUUID(),
      })
      job.track(data.job)
    } catch (e) {
      setError(String(e))
    } finally {
      setSending(false)
    }
  }
  const current: Artifact | null = artifact?.kind === 'evidence' ? artifact : null
  return (
    <WorkspaceShell
      title={t('Evidence Workspace')}
      description={t(
        'Ask questions against saved material, inspect evidence and open original PDF pages. If no evidence is retrieved, no answer is generated.'
      )}
    >
      <ErrorMessage error={error || listError || openError || job.error} />
      <form className={panel} onSubmit={submit}>
        <label className="block">
          {t('Question')}
          <textarea
            required
            minLength={3}
            maxLength={3000}
            className={input}
            value={topic}
            onChange={e => setTopic(e.target.value)}
          />
        </label>
        <div className="grid md:grid-cols-2 gap-4">
          <label>
            {t('Knowledge base')}
            <select className={input} value={kb} onChange={e => setKb(e.target.value)}>
              <option value="">{t('Select knowledge base')}</option>
              {kbs.map(value => (
                <option key={value.name}>{value.name}</option>
              ))}
            </select>
          </label>
          <label>
            {t('Notebook (optional)')}
            <select className={input} value={notebook} onChange={e => setNotebook(e.target.value)}>
              <option value="">{t('Select notebook')}</option>
              {notebooks.map(value => (
                <option key={value.id} value={value.id}>
                  {value.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          {t(
            'Notebook notes can contain model-generated text. Verify their original sources before relying on them.'
          )}
        </p>
        <button className={button} disabled={sending || job.busy || (!kb && !notebook)}>
          {t('Retrieve and answer')}
        </button>
      </form>
      <JobNotice job={job.job} />
      <label className="block">
        {t('Saved evidence')}
        <select
          className={input}
          value={current?.id || ''}
          onChange={e => {
            if (e.target.value) void open(e.target.value)
          }}
        >
          <option value="">{t('Select saved evidence')}</option>
          {items.map(value => (
            <option key={value.id} value={value.id}>
              {value.title}
            </option>
          ))}
        </select>
      </label>
      {current && (
        <>
          <section className={panel}>
            <h2 className="text-xl">{current.title}</h2>
            <p>{current.status}</p>
            <p className="text-amber-800 dark:text-amber-200 text-sm">{current.warning}</p>
            <Claims items={current.claims || []} />
            <ExportLinks id={current.id} />
            {!!current.sources?.length && (
              <Link
                className="inline-block text-blue-600 dark:text-blue-300 underline"
                href={`/study-packs?evidence=${encodeURIComponent(current.id)}`}
              >
                {t('Create sourced Study Pack')}
              </Link>
            )}
          </section>
          <Sources sources={current.sources || []} />
        </>
      )}
    </WorkspaceShell>
  )
}
