import { useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis, ReferenceLine } from 'recharts'
import { fmt, Group, int, OUTCOME, QBDetail, QBList, QBRow } from './api'
import { axis, Badge, Card, Kpi, Status, td, th, tooltipStyle, useApi } from './ui'

type SortKey = 'margen_exacto_mediana_s' | 'jugadas_analizadas' | 'margenes_exactos' | 'pct_censuradas_sobre_elegibles' | 'nombre'

export default function Quarterbacks() {
  const { data, error, loading } = useApi<QBList>('quarterbacks')
  const [sort, setSort] = useState<SortKey>('margen_exacto_mediana_s')
  const [onlyOk, setOnlyOk] = useState(false)
  const [sel, setSel] = useState<number | null>(null)
  const [q, setQ] = useState('')

  const rows = useMemo(() => {
    if (!data) return []
    let r = data.quarterbacks.filter((x) => (!onlyOk || x.muestra_suficiente) && (x.nombre ?? '').toLowerCase().includes(q.toLowerCase()))
    const stat = sort === 'margen_exacto_mediana_s'
    r = [...r].sort((a, b) => {
      if (sort === 'nombre') return (a.nombre ?? '').localeCompare(b.nombre ?? '')
      if (stat && a.muestra_suficiente !== b.muestra_suficiente) return a.muestra_suficiente ? -1 : 1
      const av = a[sort] as number | null, bv = b[sort] as number | null
      if (av === null) return 1
      if (bv === null) return -1
      return bv - av
    })
    return r
  }, [data, sort, onlyOk, q])

  const chart = useMemo(() => (data?.quarterbacks ?? []).filter((x) => x.muestra_suficiente && x.margen_exacto_mediana_s !== null)
    .sort((a, b) => (b.margen_exacto_media_s ?? 0) - (a.margen_exacto_media_s ?? 0))
    .map((x) => ({ nombre: x.nombre ?? String(x.nfl_id), media: x.margen_exacto_media_s, mediana: x.margen_exacto_mediana_s, n: x.margenes_exactos })), [data])

  if (!data) return <Status loading={loading} error={error} />
  const head = (k: SortKey, label: string) => (
    <th className={`${th} cursor-pointer hover:text-emerald-300 ${sort === k ? 'text-emerald-300' : ''}`} onClick={() => setSort(k)}>{label}{sort === k ? ' ▼' : ''}</th>
  )
  return (
    <div className="space-y-4">
      <Card title={`Margen exacto medio por QB (solo muestra suficiente: ≥ ${data.min_margenes_exactos} márgenes exactos)`}
        right={<span className="text-xs text-slate-400">{data.con_muestra_suficiente} de {data.total_quarterbacks} QBs</span>}>
        <div className="h-80">
          <ResponsiveContainer>
            <BarChart data={chart} margin={{ bottom: 70 }}>
              <CartesianGrid stroke="#1e293b" vertical={false} />
              <XAxis dataKey="nombre" {...axis} angle={-55} textAnchor="end" interval={0} height={80} />
              <YAxis {...axis} unit=" s" />
              <ReferenceLine y={0} stroke="#fbbf24" />
              <Tooltip contentStyle={tooltipStyle} formatter={(v: unknown, name: unknown) => [`${Number(v).toFixed(2)} s`, String(name)]}
                labelFormatter={(l: unknown, p: readonly { payload?: { n?: number } }[]) => `${String(l)} · n = ${p?.[0]?.payload?.n ?? '—'} márgenes exactos`} />
              <Bar dataKey="media" name="Media">
                {chart.map((c) => <Cell key={c.nombre} fill={(c.media ?? 0) < 0 ? '#f87171' : '#34d399'} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <p className="text-xs text-slate-400">Las medias excluyen jugadas censuradas (con frecuencia lanzamientos rápidos sin presión observada); compárese con el % de censuradas. Asociación descriptiva, no causal.</p>
      </Card>

      <Card title="Comparación de quarterbacks" right={
        <div className="flex items-center gap-3 text-xs text-slate-300">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar QB…" className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-sm" />
          <label className="flex items-center gap-1"><input type="checkbox" checked={onlyOk} onChange={(e) => setOnlyOk(e.target.checked)} /> solo muestra suficiente</label>
        </div>}>
        <div className="max-h-[28rem] overflow-auto">
          <table className="w-full">
            <thead className="sticky top-0 bg-slate-900">
              <tr>{head('nombre', 'QB')}<th className={th}>Equipo</th>{head('jugadas_analizadas', 'Jugadas')}{head('margenes_exactos', 'Márg. exactos')}
                <th className={th}>Antes</th><th className={th}>Simult.</th><th className={th}>Después</th><th className={th}>Censuradas</th>
                {head('pct_censuradas_sobre_elegibles', '% censur.')}{head('margen_exacto_mediana_s', 'Mediana (s)')}<th className={th}>Media (s)</th><th className={th}>Muestra</th></tr>
            </thead>
            <tbody>
              {rows.map((r: QBRow) => (
                <tr key={r.nfl_id} onClick={() => setSel(r.nfl_id)} className={`cursor-pointer border-t border-slate-800 hover:bg-slate-800/60 ${sel === r.nfl_id ? 'bg-emerald-950/40' : ''}`}>
                  <td className={`${td} font-medium`}>{r.nombre}</td><td className={td}>{r.equipos.join(', ')}</td>
                  <td className={td}>{r.jugadas_analizadas}</td><td className={td}>{r.margenes_exactos}</td>
                  <td className={td}>{r.presion_antes_del_lanzamiento}</td><td className={td}>{r.simultaneas}</td><td className={td}>{r.presion_despues_del_lanzamiento}</td>
                  <td className={td}>{r.censuradas}</td><td className={td}>{fmt(r.pct_censuradas_sobre_elegibles, 1, ' %')}</td>
                  <td className={td}>{fmt(r.margen_exacto_mediana_s, 1)}</td><td className={td}>{fmt(r.margen_exacto_media_s, 2)}</td>
                  <td className={td}><Badge ok={r.muestra_suficiente}>{r.muestra_suficiente ? 'suficiente' : 'insuficiente'}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-slate-400">Haz clic en un QB para ver sus desgloses. Con muestra insuficiente no se muestran mediana ni media.</p>
      </Card>

      {sel !== null && <QBPanel id={sel} />}
    </div>
  )
}

function QBPanel({ id }: { id: number }) {
  const { data, error, loading } = useApi<QBDetail>(`quarterbacks/${id}`)
  if (!data) return <Status loading={loading} error={error} />
  const r = data.resumen
  const label = (k: string, v: Group['valor']) => (k === 'resultado' ? OUTCOME[String(v)] ?? String(v) : k === 'down' ? `${v}º down` : String(v ?? '—'))
  const titles: Record<string, string> = { formacion: 'Formación ofensiva', cobertura: 'Cobertura defensiva', down: 'Down', distancia_por_avanzar: 'Yardas por avanzar', resultado: 'Resultado' }
  return (
    <Card title={`Detalle: ${data.nombre} (${data.equipos.join(', ')})`}>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Kpi label="Jugadas" value={int(r.jugadas)} accent="text-slate-100" />
        <Kpi label="Márgenes exactos" value={int(r.margenes_exactos)} sub={r.muestra_suficiente ? 'muestra suficiente' : `muestra insuficiente (< ${r.min_margenes_exactos})`} accent="text-sky-400" />
        <Kpi label="Margen exacto mediano" value={fmt(r.margen_exacto_mediana_s, 1, ' s')} sub={`media ${fmt(r.margen_exacto_media_s, 2, ' s')}`} />
        <Kpi label="Censuradas" value={int(r.jugadas_censuradas)} sub={`${fmt(r.pct_censuradas_sobre_elegibles, 1, ' %')} de elegibles`} accent="text-blue-400" />
        <Kpi label="Lanzamiento mediano" value={fmt(r.tiempo_lanzamiento_s.mediana, 1, ' s')} sub={`n = ${r.tiempo_lanzamiento_s.n}`} accent="text-slate-100" />
      </div>
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        {(Object.keys(titles) as (keyof QBDetail['desgloses'])[]).map((k) => (
          <div key={k} className="rounded-lg border border-slate-800 p-2">
            <div className="mb-1 text-xs font-semibold uppercase text-slate-400">{titles[k]}</div>
            <table className="w-full">
              <thead><tr><th className={th}>Valor</th><th className={th}>Jugadas</th><th className={th}>Exactos</th><th className={th}>Antes</th><th className={th}>Simult.</th><th className={th}>Después</th><th className={th}>Censur.</th><th className={th}>Mediana (s)</th></tr></thead>
              <tbody>
                {data.desgloses[k].map((g) => (
                  <tr key={String(g.valor)} className="border-t border-slate-800">
                    <td className={td}>{label(k, g.valor)}</td><td className={td}>{g.jugadas}</td><td className={td}>{g.margenes_exactos}</td>
                    <td className={td}>{g.categorias.pressure_before_throw}</td><td className={td}>{g.categorias.simultaneous_pressure_and_throw}</td>
                    <td className={td}>{g.categorias.pressure_after_throw}</td><td className={td}>{g.jugadas_censuradas}</td>
                    <td className={td}>{g.muestra_suficiente ? fmt(g.margen_exacto_mediana_s, 1) : <span className="text-slate-500">n &lt; {data.min_margenes_exactos_desglose}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </Card>
  )
}
