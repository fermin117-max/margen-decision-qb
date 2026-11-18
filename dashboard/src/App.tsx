import { useEffect, useState } from 'react'
import { api, Filters, Status as St, Summary } from './api'
import Overview from './Overview'
import Quarterbacks from './Quarterbacks'
import Defenders from './Defenders'
import Formations from './Formations'
import Plays from './Plays'
import { Status, useApi } from './ui'

const TABS = [
  ['resumen', 'Resumen'], ['qbs', 'Quarterbacks'], ['defensores', 'Defensores'], ['formaciones', 'Formación y cobertura'], ['jugadas', 'Explorador de jugadas'],
] as const
type Tab = (typeof TABS)[number][0]

function useBackendReady() {
  const [st, setSt] = useState<St | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    let t: number | undefined
    const poll = () => api<St>('status').then((s) => {
      if (!alive) return
      setSt(s); setErr(null)
      if (s.state !== 'ready' && s.state !== 'error') t = window.setTimeout(poll, 1500)
    }).catch(() => { if (alive) { setErr('No se pudo conectar con la API. Reintentando…'); t = window.setTimeout(poll, 3000) } })
    poll()
    return () => { alive = false; if (t) window.clearTimeout(t) }
  }, [])
  return { st, err }
}

export default function App() {
  const [tab, setTab] = useState<Tab>('resumen')
  const { st, err } = useBackendReady()
  const ready = st?.state === 'ready'
  const summary = useApi<Summary>(ready ? 'summary' : null)
  const filters = useApi<Filters>(ready ? 'filters' : null)

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 bg-gradient-to-r from-slate-950 via-slate-900 to-emerald-950/40">
        <div className="mx-auto max-w-7xl px-4 py-5">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.3em] text-emerald-400">NFL Big Data Bowl · UNAM</div>
              <h1 className="mt-1 text-3xl font-black tracking-tight md:text-4xl">QB <span className="text-emerald-400">DECISION</span> <span className="text-sky-400">MARGIN</span></h1>
              <p className="mt-1 text-slate-300">Análisis de presión defensiva y tiempo de decisión del quarterback.</p>
            </div>
            <div className="text-right text-xs text-slate-400">
              <div>Margen = tiempo hasta la presión − tiempo de lanzamiento</div>
              <div>Tracking a 10 FPS · resolución ≈ 0.1 s</div>
            </div>
          </div>
          <nav className="mt-4 flex flex-wrap gap-1">
            {TABS.map(([k, label]) => (
              <button key={k} onClick={() => setTab(k)}
                className={`rounded-md px-3 py-1.5 text-sm font-medium ${tab === k ? 'bg-emerald-500 text-slate-950' : 'text-slate-300 hover:bg-slate-800'}`}>{label}</button>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-4 px-4 py-5">
        {!ready && (
          <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-6 text-center">
            {st?.state === 'error'
              ? <p className="text-red-300">Error al calcular las métricas: {st.error}</p>
              : <p className="animate-pulse text-slate-300">{err ?? 'El backend está procesando los 122 archivos de tracking (≈20-60 s). Las cifras aparecerán al terminar.'}</p>}
          </div>
        )}
        {ready && tab === 'resumen' && (summary.data ? <Overview s={summary.data} /> : <Status loading={summary.loading} error={summary.error} />)}
        {ready && tab === 'qbs' && <Quarterbacks />}
        {ready && tab === 'defensores' && <Defenders />}
        {ready && tab === 'formaciones' && <Formations />}
        {ready && tab === 'jugadas' && (filters.data ? <Plays filters={filters.data} /> : <Status loading={filters.loading} error={filters.error} />)}

        <section className="rounded-xl border border-sky-900/60 bg-sky-950/20 p-4 text-sm text-slate-300">
          <h2 className="mb-2 font-semibold uppercase tracking-wide text-sky-300">Nota metodológica</h2>
          <ul className="list-disc space-y-1 pl-5">
            <li>La presión es una <b>definición operacional del equipo</b>, no un criterio oficial de la NFL: un pass rusher (rol PFF «Pass Rush») entra a ≤ 2.0 yardas del QB después del snap y permanece 2 frames consecutivos.</li>
            <li>El tracking trabaja a 10 FPS: los tiempos tienen una resolución aproximada de 0.1 s.</li>
            <li>El tracking termina ≈ 0.5 s después del lanzamiento. Por eso el margen positivo exacto está limitado (~0.4 s) y <b>no mide todo el tiempo libre del QB</b>.</li>
            <li>Las jugadas <b>censuradas</b> (presión no observada antes del fin del tracking) se muestran por separado y <b>nunca</b> entran en medias ni medianas de márgenes exactos. No significan que no hubo presión.</li>
            <li>Hits, hurries y sacks son etiquetas de PFF y se muestran aparte de la presión detectada por tracking.</li>
            <li>Todas las comparaciones son asociaciones descriptivas con su tamaño de muestra; no implican causalidad.</li>
          </ul>
        </section>
      </main>
      <footer className="pb-6 text-center text-xs text-slate-500">Datos: NFL Big Data Bowl (122 juegos de la temporada 2021). Cifras calculadas en vivo por la API.</footer>
    </div>
  )
}
