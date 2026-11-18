import { useState } from 'react'
import { CAT, Filters, fmt, int, OUTCOME, Play, PlayDetail, PlayPage } from './api'
import { Card, Select, Status, td, th, useApi } from './ui'

const PAGE = 25
type F = { qb_id: string; defender_id: string; formation: string; coverage: string; down: string; margin_category: string; outcome: string }
const EMPTY: F = { qb_id: '', defender_id: '', formation: '', coverage: '', down: '', margin_category: '', outcome: '' }

function CatTag({ c }: { c: string }) {
  const m = CAT[c]
  return <span className="rounded px-1.5 py-0.5 text-[11px] font-semibold text-slate-950" style={{ background: m?.color ?? '#64748b' }}>{m?.label ?? c}</span>
}

function MarginCell({ p }: { p: Play }) {
  if (p.margin_is_exact) return <span className={(p.decision_margin_s ?? 0) < 0 ? 'text-red-300' : (p.decision_margin_s ?? 0) > 0 ? 'text-emerald-300' : 'text-amber-200'}>{fmt(p.decision_margin_s, 1, ' s')}</span>
  if (p.margin_category === 'pressure_not_observed_censored') return <span className="text-blue-300">≥ {fmt(p.observed_margin_lower_bound_s, 1, ' s')} <span className="text-[10px] text-slate-400">(cota)</span></span>
  return <span className="text-slate-500">—</span>
}

export default function Plays({ filters }: { filters: Filters }) {
  const [f, setF] = useState<F>(EMPTY)
  const [page, setPage] = useState(0)
  const [sel, setSel] = useState<{ g: number; p: number } | null>(null)
  const { data, error, loading } = useApi<PlayPage>('plays', { ...f, limit: PAGE, offset: page * PAGE })
  const set = (k: keyof F) => (v: string) => { setF({ ...f, [k]: v }); setPage(0); setSel(null) }
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE)) : 1
  return (
    <div className="space-y-4">
      <Card title="Filtros">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
          <Select label="Quarterback" value={f.qb_id} onChange={set('qb_id')} options={filters.quarterbacks.map((q) => ({ value: String(q.nfl_id), label: `${q.nombre} (${q.jugadas})` }))} />
          <Select label="Defensor (pass rusher)" value={f.defender_id} onChange={set('defender_id')} options={filters.defensores.map((d) => ({ value: String(d.nfl_id), label: `${d.nombre} (${d.jugadas_como_pass_rusher})` }))} />
          <Select label="Formación" value={f.formation} onChange={set('formation')} options={filters.formaciones.map((o) => ({ value: String(o.valor), label: `${o.valor} (${o.jugadas})` }))} />
          <Select label="Cobertura" value={f.coverage} onChange={set('coverage')} options={filters.coberturas.map((o) => ({ value: String(o.valor), label: `${o.valor} (${o.jugadas})` }))} />
          <Select label="Down" value={f.down} onChange={set('down')} options={filters.downs.map((o) => ({ value: String(o.valor), label: `${o.valor} (${o.jugadas})` }))} />
          <Select label="Categoría del margen" value={f.margin_category} onChange={set('margin_category')} options={filters.categorias_margen.filter((o) => o.jugadas > 0).map((o) => ({ value: String(o.valor), label: `${CAT[String(o.valor)]?.label ?? o.valor} (${o.jugadas})` }))} />
          <Select label="Resultado" value={f.outcome} onChange={set('outcome')} options={filters.resultados.map((o) => ({ value: String(o.valor), label: `${OUTCOME[String(o.valor)] ?? o.valor} (${o.jugadas})` }))} />
        </div>
        <button onClick={() => { setF(EMPTY); setPage(0); setSel(null) }} className="mt-3 rounded-md border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:border-emerald-500">Limpiar filtros</button>
      </Card>

      <Status loading={loading && !data} error={error} />
      {data && (
        <Card title={`${int(data.total)} jugadas`} right={
          <div className="flex flex-wrap gap-2 text-xs text-slate-400">
            {Object.entries(data.categorias).filter(([, v]) => v > 0).map(([k, v]) => <span key={k}><span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: CAT[k]?.color }} />{CAT[k]?.label ?? k}: {v}</span>)}
            <span className="text-slate-300">· margen exacto medio {fmt(data.margen_exacto.media, 2, ' s')} (n = {data.margen_exacto.n})</span>
          </div>}>
          <div className="overflow-auto">
            <table className="w-full">
              <thead><tr>{['Partido / jugada', 'QB', 'Down', 'Formación', 'Cobertura', 'Resultado', 'Lanzamiento', 'Presión', 'Margen', 'Categoría', 'Llegaron', 'PFF', 'Revisión'].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
              <tbody>
                {data.jugadas.map((p) => (
                  <tr key={`${p.gameId}-${p.playId}`} onClick={() => setSel({ g: p.gameId, p: p.playId })}
                    className={`cursor-pointer border-t border-slate-800 hover:bg-slate-800/60 ${sel?.g === p.gameId && sel?.p === p.playId ? 'bg-emerald-950/40' : ''}`}>
                    <td className={td}>{p.gameId} / {p.playId}</td><td className={td}>{p.qb_nombre}</td>
                    <td className={td}>{p.down} & {p.yardsToGo}</td><td className={td}>{p.offenseFormation ?? '—'}</td><td className={td}>{p.pff_passCoverage ?? '—'}</td>
                    <td className={td}>{OUTCOME[p.outcome ?? ''] ?? p.outcome}</td>
                    <td className={td}>{fmt(p.throw_time_s, 1, ' s')}</td><td className={td}>{fmt(p.pressure_time_s, 1, ' s')}</td>
                    <td className={td}><MarginCell p={p} /></td><td className={td}><CatTag c={p.margin_category} /></td>
                    <td className={td}>{p.pressure_defenders.map((d) => d.nombre).join(', ') || '—'}{p.pressure_tie ? ' (empate)' : ''}</td>
                    <td className={td}>{[p.pff_sack ? `sack ${p.pff_sack}` : '', p.pff_hit ? `hit ${p.pff_hit}` : '', p.pff_hurry ? `hurry ${p.pff_hurry}` : ''].filter(Boolean).join(' · ') || '—'}</td>
                    <td className={`${td} text-amber-300`}>{p.review_flags.length ? p.review_flags.join(', ') : ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex items-center gap-3 text-sm text-slate-300">
            <button disabled={page === 0} onClick={() => setPage(page - 1)} className="rounded-md border border-slate-700 px-3 py-1 disabled:opacity-40">← Anterior</button>
            <span>Página {page + 1} de {pages}</span>
            <button disabled={page + 1 >= pages} onClick={() => setPage(page + 1)} className="rounded-md border border-slate-700 px-3 py-1 disabled:opacity-40">Siguiente →</button>
          </div>
        </Card>
      )}
      {sel && <PlayPanel g={sel.g} p={sel.p} />}
    </div>
  )
}

function PlayPanel({ g, p }: { g: number; p: number }) {
  const { data, error, loading } = useApi<PlayDetail>(`plays/${g}/${p}`)
  if (!data) return <Status loading={loading} error={error} />
  return (
    <Card title={`Jugada ${data.gameId} / ${data.playId} · ${data.possessionTeam} vs ${data.defensiveTeam}`}>
      <p className="text-sm text-slate-300">{data.playDescription}</p>
      <div className="mt-3 grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
        <div>Snap: frame {data.snap_frame ?? '—'} <span className="text-slate-400">({data.snap_event ?? 'sin evento'}{data.snap_source ? `, ${data.snap_source}` : ''})</span></div>
        <div>Lanzamiento: frame {data.throw_frame ?? '—'} <span className="text-slate-400">({data.throw_event ?? 'sin evento'}{data.throw_source ? `, ${data.throw_source}` : ''})</span></div>
        <div>Presión: frame {data.pressure_frame ?? '—'} · {fmt(data.pressure_time_s, 1, ' s')}</div>
        <div>Último frame de tracking: {data.last_frame}</div>
        <div>Margen: <MarginCell p={data} /></div><div><CatTag c={data.margin_category} /></div>
        <div>Proximidad en el snap: {data.preexisting_proximity_at_snap ? 'sí' : 'no'}</div>
        <div className="text-amber-300">{data.review_flags.join(', ')}</div>
      </div>
      <table className="mt-3 w-full">
        <thead><tr>{['Pass rusher', 'Pos.', 'Cerca en snap', 'Llegó', 'Tiempo', 'Dist. (yd)', 'Primero', 'PFF sack', 'PFF hit', 'PFF hurry'].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
        <tbody>
          {data.pass_rushers.map((r) => (
            <tr key={r.nflId} className="border-t border-slate-800">
              <td className={td}>{r.nombre}</td><td className={td}>{r.pff_positionLinedUp}</td><td className={td}>{r.within_at_snap ? 'sí' : ''}</td>
              <td className={td}>{r.arrived ? 'sí' : ''}</td><td className={td}>{fmt(r.arrival_time_s, 1, ' s')}</td><td className={td}>{fmt(r.dist_at_arrival_yd, 2)}</td>
              <td className={td}>{r.first_to_arrive ? '★' : ''}</td><td className={td}>{r.pff_sack || ''}</td><td className={td}>{r.pff_hit || ''}</td><td className={td}>{r.pff_hurry || ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  )
}
