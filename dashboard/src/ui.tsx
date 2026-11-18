import { ReactNode, useEffect, useState } from 'react'
import { api, ApiError } from './api'

export function useApi<T>(path: string | null, params?: Record<string, string | number | undefined | null>) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const key = path + JSON.stringify(params ?? {})
  useEffect(() => {
    if (!path) return
    let alive = true
    let timer: number | undefined
    const run = () => {
      setLoading(true)
      api<T>(path, params)
        .then((d) => { if (alive) { setData(d); setError(null); setLoading(false) } })
        .catch((e: unknown) => {
          if (!alive) return
          const err = e instanceof ApiError ? e : null
          setError(err ? err.message : 'No se pudo conectar con la API.')
          setLoading(false)
          if (err?.status === 503) timer = window.setTimeout(run, 2000)
        })
    }
    run()
    return () => { alive = false; if (timer) window.clearTimeout(timer) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  return { data, error, loading }
}

export function Card({ title, children, right, className = '' }: { title?: ReactNode; children: ReactNode; right?: ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-slate-800 bg-slate-900/70 p-4 ${className}`}>
      {(title || right) && (
        <div className="mb-3 flex items-start justify-between gap-2">
          {title && <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-300">{title}</h3>}
          {right}
        </div>
      )}
      {children}
    </section>
  )
}

export function Kpi({ label, value, sub, accent = 'text-emerald-400' }: { label: string; value: ReactNode; sub?: ReactNode; accent?: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-4">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`mt-1 text-3xl font-bold tabular-nums ${accent}`}>{value}</div>
      {sub && <div className="mt-1 text-xs text-slate-400">{sub}</div>}
    </div>
  )
}

export function Status({ loading, error }: { loading: boolean; error: string | null }) {
  if (error) return <div className="rounded-lg border border-amber-700 bg-amber-950/40 p-3 text-sm text-amber-200">{error}</div>
  if (loading) return <div className="animate-pulse p-3 text-sm text-slate-400">Cargando datos reales…</div>
  return null
}

export function Badge({ ok, children }: { ok: boolean; children: ReactNode }) {
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${ok ? 'bg-emerald-900/60 text-emerald-300' : 'bg-slate-800 text-slate-400'}`}>{children}</span>
  )
}

export const th = 'px-2 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-slate-400 whitespace-nowrap'
export const td = 'px-2 py-1.5 text-sm text-slate-200 whitespace-nowrap tabular-nums'

export const tooltipStyle = { backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: 8, color: '#e2e8f0' }
export const axis = { stroke: '#94a3b8', fontSize: 11 }

export function Select({ label, value, onChange, options }: {
  label: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[]
}) {
  return (
    <label className="flex flex-col gap-1 text-xs text-slate-400">
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100 focus:border-emerald-500 focus:outline-none">
        <option value="">Todos</option>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  )
}
