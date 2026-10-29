'use client'
import { useTranslation } from 'react-i18next'
import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import {useRouter} from 'next/navigation'
import {
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

export default function StudyPacksPage() {
  const { t } = useTranslation()
  const router=useRouter()

  const [evidence, setEvidence] = useState('')
  const [error, setError] = useState('')
  const [sending, setSending] = useState(false)
  const evidenceList = useArtifacts('evidence')
  const {items:packItems,refresh:refreshPacks,error:packError} = useArtifacts('study_pack')
  const { artifact, open, error: openError } = useActiveArtifact()
  const done = useCallback(
    (id: string) => {
      void open(id)
      void refreshPacks()
    },
    [open, refreshPacks]
  )
  const job = useDurableJob('study-pack', done)
  useEffect(() => {
    const timer = setTimeout(
      () => setEvidence(new URLSearchParams(window.location.search).get('evidence') || ''),
      0
    )
    return () => clearTimeout(timer)
  }, [])
  async function generate() {
    setSending(true)
    setError('')
    try {
      const data = await request<{ job: Job }>('/api/v1/learning/study-packs', {
        evidence_id: evidence,
        request_id: crypto.randomUUID(),
      })
      job.track(data.job)
    } catch (e) {
      setError(String(e))
    } finally {
      setSending(false)
    }
  }
  async function enroll() {
    if (!artifact) return
    setError('')
    try {
      await request(`/api/v1/learning/study-packs/${encodeURIComponent(artifact.id)}/review`, {})
      router.push('/review')
    } catch (e) {
      setError(String(e))
    }
  }
  const current = artifact?.kind === 'study_pack' ? artifact : null
  return (
    <WorkspaceShell
      title={t('Sourced Study Packs')}
      description={t(
        'Learning goals, summary, concept relationships, quiz explanations and a rubric, all linked to the same evidence snapshot.'
      )}
    >
      <ErrorMessage error={error || packError || evidenceList.error || openError || job.error} />
      <section className={panel}>
        <label>
          {t('Evidence snapshot')}
          <select className={input} value={evidence} onChange={e => setEvidence(e.target.value)}>
            <option value="">{t('Select evidence')}</option>
            {evidenceList.items.map(value => (
              <option key={value.id} value={value.id}>
                {value.title}
              </option>
            ))}
          </select>
        </label>
        <button
          className={button}
          disabled={!evidence || sending || job.busy}
          onClick={() => void generate()}
        >
          {t('Generate Study Pack')}
        </button>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          {t(
            'Generated material still needs your review. Unknown citations and malformed questions are rejected.'
          )}
        </p>
      </section>
      <JobNotice job={job.job} />
      <label>
        {t('Saved Study Packs')}
        <select
          className={input}
          value={current?.id || ''}
          onChange={e => {
            if (e.target.value) void open(e.target.value)
          }}
        >
          <option value="">{t('Select Study Pack')}</option>
          {packItems.map(value => (
            <option key={value.id} value={value.id}>
              {value.title}
            </option>
          ))}
        </select>
      </label>
      {current?.pack && (
        <>
          <section className={panel}>
            <h2 className="text-2xl">{current.title}</h2>
            <ExportLinks id={current.id} />
            <button className={button} onClick={() => void enroll()}>
              {t('Add quiz to Adaptive Review')}
            </button>
            <p className="text-sm">
              {t('To make slides, download the text (.txt) pack and upload it to')}{' '}
              <Link href="/slide_pro" className="text-blue-600 dark:text-blue-300 underline">
                {t('Slide Generator')}
              </Link>
              {t(', powered by')}{' '}
              <a
                href="https://github.com/presenton/presenton"
                target="_blank"
                rel="noreferrer"
                className="underline text-blue-600 dark:text-blue-300"
              >
                {t('Presenton')}
              </a>
              {t('.')}
            </p>
          </section>
          {(['goals', 'summary', 'concepts', 'rubric'] as const).map(section => (
            <section key={section} className={panel}>
              <h2 className="text-xl capitalize">{section}</h2>
              <Claims items={current.pack![section]} />
            </section>
          ))}
          <section className={panel}>
            <h2 className="text-xl">{t('Quiz')}</h2>
            {current.pack.quiz.map((question, index) => (
              <article key={index} className="border-t border-slate-700 py-4">
                <Claims items={[question]} />
                <ol className="list-decimal pl-6 mt-3">
                  {question.options.map((option, i) => (
                    <li key={i}>{option}</li>
                  ))}
                </ol>
                <details className="mt-2">
                  <summary className="cursor-pointer text-blue-600 dark:text-blue-300">
                    {t('Answer and explanation')}
                  </summary>
                  <p>
                    {question.answer + 1}
                    {t('.')} {question.explanation}
                  </p>
                </details>
              </article>
            ))}
          </section>
          <Sources sources={current.sources || []} />
        </>
      )}
    </WorkspaceShell>
  )
}
