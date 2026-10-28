'use client'
import { useTranslation } from 'react-i18next'
import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { apiUrl } from '@/lib/api'
import {
  Claim,
  ErrorMessage,
  WorkspaceShell,
  button,
  input,
  panel,
  request,
} from '@/components/learning/shared'
type Card = {
  id: string
  pack_id: string
  due: number
  is_due: boolean
  repetitions: number
  lapses: number
  item: Claim & { topic: string; options: string[] }
}
type Review = {
  cards: Card[]
  topics: { topic: string; attempts: number; correct: number }[]
  attempts: number
  algorithm: string
}
type Result = {
  correct: boolean
  answer: number
  explanation: string
  source_ids: string[]
  next_due: number
}
export default function ReviewPage() {
  const { t } = useTranslation()

  const [data, setData] = useState<Review | null>(null)
  const [error, setError] = useState('')
  const [answer, setAnswer] = useState(-1)
  const [rating, setRating] = useState(2)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<Result | null>(null)
  const [reviewed, setReviewed] = useState<Card | null>(null)
  const refresh = useCallback(async () => {
    try {
      setData(await request<Review>('/api/v1/learning/review'))
      setError('')
    } catch (e) {
      setError(String(e))
    }
  }, [])
  useEffect(() => {
    const timer = setTimeout(() => void refresh(), 0)
    return () => clearTimeout(timer)
  }, [refresh])
  async function importBackup(file: File | undefined) {
    if (!file) return
    if (file.size > 20 * 1024 * 1024) {
      setError(t('Learning backup limit is 20 MiB'))
      return
    }
    setBusy(true)
    setError('')
    try {
      await request('/api/v1/learning/import', JSON.parse(await file.text()))
      await refresh()
    } catch (error) {
      setError(
        error instanceof SyntaxError
          ? t('Invalid learning backup JSON. Choose an exported JSON backup.')
          : String(error)
      )
    } finally {
      setBusy(false)
    }
  }
  const card = data?.cards.find(item => item.is_due)
  async function submit() {
    if (!card) return
    setBusy(true)
    setError('')
    try {
      const value = await request<Result>(
        `/api/v1/learning/review/${encodeURIComponent(card.id)}/answer`,
        { answer, rating, request_id: crypto.randomUUID() }
      )
      setResult(value)
      setReviewed(card)
      await refresh()
      setAnswer(-1)
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <WorkspaceShell
      title={t('Adaptive Review')}
      description={t(
        'A personal due queue based on your quiz answers. Progress survives refreshes and server restarts.'
      )}
    >
      <ErrorMessage error={error} />
      <section className={panel}>
        <p>
          {data?.cards.filter(item => item.is_due).length || 0} {t('due ·')}{' '}
          {data?.cards.length || 0} {t('enrolled cards ·')} {data?.attempts || 0}{' '}
          {t('recorded attempts (latest 500)')}
        </p>
        <p className="text-sm text-slate-500 dark:text-slate-400">{data?.algorithm}</p>
        <a
          className="text-blue-600 dark:text-blue-300 underline"
          href={apiUrl('/api/v1/learning/export')}
        >
          {t('Download learning backup (sources, packs, review history)')}
        </a>
        <label className="block text-sm">
          {t('Restore learning backup (merge without overwriting local progress)')}
          <input
            type="file"
            accept="application/json,.json"
            disabled={busy || !data}
            className="block mt-2"
            onChange={event => {
              const file = event.target.files?.[0]
              event.target.value = ''
              void importBackup(file)
            }}
          />
        </label>
      </section>
      {result && (
        <section className={panel} role="status">
          <h2 className="text-xl">{result.correct ? 'Correct' : 'Review this concept'}</h2>
          <p>
            {t('Answer:')} {reviewed?.item.options[result.answer] || result.answer + 1}
          </p>
          <p>{result.explanation}</p>
          <p>
            {t('Next review:')} {new Date(result.next_due * 1000).toLocaleString()}
          </p>
          <Link
            className="text-blue-600 dark:text-blue-300 underline"
            href={`/study-packs?artifact=${encodeURIComponent(reviewed?.pack_id || '')}`}
          >
            {t('Inspect explanation sources in Study Pack')}
          </Link>
          <button className={button + ' ml-4'} onClick={() => setResult(null)}>
            {t('Continue')}
          </button>
        </section>
      )}
      {!result && card ? (
        <form
          className={panel}
          onSubmit={event => {
            event.preventDefault()
            void submit()
          }}
        >
          <p className="text-blue-600 dark:text-blue-300">{card.item.topic}</p>
          <h2 className="text-xl">{card.item.text}</h2>
          <fieldset className="space-y-3">
            <legend className="sr-only">{t('Choose an answer')}</legend>
            {card.item.options.map((option, index) => (
              <label
                key={index}
                className="flex items-start gap-3 rounded-lg border border-slate-700 p-3"
              >
                <input
                  type="radio"
                  required
                  name="answer"
                  checked={answer === index}
                  onChange={() => setAnswer(index)}
                />
                {option}
              </label>
            ))}
          </fieldset>
          <label>
            {t('How well do you remember this?')}
            <select
              className={input}
              value={rating}
              onChange={event => setRating(Number(event.target.value))}
            >
              {[
                'Again — 10 minutes',
                'Hard — at least 1 day',
                'Good — normal spacing',
                'Easy — longer spacing',
              ].map((text, index) => (
                <option key={index} value={index}>
                  {text}
                </option>
              ))}
            </select>
          </label>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t(
              'An incorrect answer always resets the card to 10 minutes, regardless of your selected rating.'
            )}
          </p>
          <button className={button} disabled={busy || answer < 0}>
            {t('Check answer and schedule review')}
          </button>
        </form>
      ) : (
        !result && (
          <p className={panel}>
            {t('No cards are due. Generate a')}{' '}
            <Link href="/study-packs" className="text-blue-600 dark:text-blue-300 underline">
              {t('Study Pack')}
            </Link>{' '}
            {t('and enroll its quiz, or return at the next scheduled time.')}
          </p>
        )
      )}
      <section className={panel}>
        <h2 className="text-xl">{t('Topic performance')}</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          {t('Observed answer accuracy, not a prediction of mastery.')}
        </p>
        {data?.topics.map(topic => (
          <p key={topic.topic}>
            {topic.topic}
            {t(':')} {topic.correct}
            {t('/')}
            {topic.attempts} {t('correct (')}
            {Math.round((topic.correct / topic.attempts) * 100)}
            {t('%)')}
          </p>
        ))}
      </section>
      <section className={panel}>
        <h2 className="text-xl">{t('Upcoming reviews')}</h2>
        {data?.cards
          .filter(item => !item.is_due)
          .map(item => (
            <p key={item.id}>
              {item.item.topic} {t('·')} {new Date(item.due * 1000).toLocaleString()} {t('·')}{' '}
              {item.lapses} {t('lapses')}
            </p>
          ))}
      </section>
    </WorkspaceShell>
  )
}
