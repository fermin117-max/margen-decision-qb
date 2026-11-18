import { useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, Legend } from 'recharts'
import { DefList, DefRow, fmt } from './api'
import { axis, Badge, Card, Status, td, th, tooltipStyle, useApi } from './ui'

type K = 'presiones_detectadas_tracking' | 'tiempo_hasta_presion_mediana_s' | 'pff_sacks' | 'pff_hits' | 'pff_hurries' | 'jugadas_como_pass_rusher' | 'tasa_presion_tracking'

export default function Defenders() {
  const { data, error, loading } = useApi<DefList>('defenders')
  const [sort, setSort] = useState<K>('presiones_detectadas_tracking')
  const [q, setQ] = useState('')
  const rows = useMemo(() => {
    if (!data) return []
    const asc = sort === 'tiempo_hasta_presion_mediana_s'
    return data.defensores.filter((d) => (d.nombre ?? '').toLowerCase().includes(q.toLowerCase())).sort((a, b) => {
      if (asc && a.muestra_suficiente !== b.muestra_suficiente) return a.muestra_suficiente ? -1 : 1
      const av = a[sort] as number | null, bv = b[sort] as number | null
      if (av === null) return 1
      if (bv === null) return -1
      return asc ? av - bv : bv - av
    }).slice(0, 200)
  }, [data, sort, q])
  const chart = useMemo(() => (data?.defensores ?? []).filter((d) => d.muestra_suficiente && d.tiempo_hasta_presion_mediana_s !== null && d.presiones_detectadas_tracking >= 20)
    .sort((a, b) => b.presiones_detectadas_tracking - a.presiones_detectadas_tracking).slice(0, 20)
    .map((d) => ({ nombre: d.nombre, mediana: d.tiempo_hasta_presion_mediana_s, media: d.tiempo_hasta_presion_media_s, n: d.presiones_detectadas_tracking })), [data])
  if (!data) return <Status loading={loading} error={error} />
  const head = (k: K, label: string, cls = '') => (
    <th className={`${th} cursor-pointer hover:text-emerald-300 ${sort === k ? 'text-emerald-300' : ''} ${cls}`} onClick={() => setSort(k)}>{label}{sort === k ? ' ▼' : ''}</th>
  )
  return (
    <div className="space-y-4">
      <Card title="Tiempo hasta la presión (tracking) · 20 pass rushers con más presiones detectadas"
        right={<span className="text-xs text-slate-400">muestra ≥ {data.min_jugadas_como_pass_rusher} jugadas como pass rusher y ≥ 20 presiones</span>}>
        <div className="h-80">
          <ResponsiveContainer>
            <BarChart data={chart} margin={{ bottom: 70 }}>
              <CartesianGrid stroke="#1e293b" vertical={false} />
              <XAxis dataKey="nombre" {...axis} angle={-55} textAnchor="end" interval={0} height={80} />
              <YAxis {...axis} unit=" s" />
              <Tooltip contentStyle={tooltipStyle} formatter={(v: unknown, n: unknown) => [`${Number(v).toFixed(2)} s`, String(n)]}
                labelFormatter={(l: unknown, p: readonly { payload?: { n?: number } }[]) => `${String(l)} · n = ${p?.[0]?.payload?.n ?? '—'} presiones`} />
              <Legend wrapperStyle={{ fontSize: 12, color: '#cbd5e1' }} verticalAlign="top" />
              <Bar dataKey="mediana" name="Mediana" fill="#34d399" />
              <Bar dataKey="media" name="Media" fill="#38bdf8" />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <p className="text-xs text-slate-400">El tiempo solo existe cuando el defensor llegó (definición operacional ≤ 2 yd, 2 frames). Solo jugadores con rol PFF «Pass Rush»; no se atribuyen intercepciones.</p>
      </Card>

      <Card title="Pass rushers" right={<input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar defensor…" className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-sm" />}>
        <div className="max-h-[30rem] overflow-auto">
          <table className="w-full">
            <thead className="sticky top-0 bg-slate-900">
              <tr>
                <th className={th}>Defensor</th><th className={th}>Pos.</th>{head('jugadas_como_pass_rusher', 'Jugadas rush')}
                <th className={`${th} border-l border-emerald-800 text-emerald-300`} colSpan={4}>Tracking (definición propia)</th>
                <th className={`${th} border-l border-sky-800 text-sky-300`} colSpan={3}>Etiquetas PFF</th><th className={th}>Muestra</th>
              </tr>
              <tr>
                <th className={th} /><th className={th} /><th className={th} />
                {head('presiones_detectadas_tracking', 'Presiones', 'border-l border-emerald-800')}{head('tasa_presion_tracking', 'Tasa')}
                {head('tiempo_hasta_presion_mediana_s', 'Mediana (s)')}<th className={th}>Media (s)</th>
                {head('pff_sacks', 'Sacks', 'border-l border-sky-800')}{head('pff_hits', 'Hits')}{head('pff_hurries', 'Hurries')}<th className={th} />
              </tr>
            </thead>
            <tbody>
              {rows.map((d: DefRow) => (
                <tr key={d.nfl_id} className="border-t border-slate-800 hover:bg-slate-800/60">
                  <td className={`${td} font-medium`}>{d.nombre}</td><td className={td}>{d.posicion_oficial}</td><td className={td}>{d.jugadas_como_pass_rusher}</td>
                  <td className={`${td} border-l border-emerald-900`}>{d.presiones_detectadas_tracking}</td><td className={td}>{fmt(d.tasa_presion_tracking === null ? null : d.tasa_presion_tracking * 100, 1, ' %')}</td>
                  <td className={td}>{fmt(d.tiempo_hasta_presion_mediana_s, 1)}</td><td className={td}>{fmt(d.tiempo_hasta_presion_media_s, 2)}</td>
                  <td className={`${td} border-l border-sky-900`}>{d.pff_sacks}</td><td className={td}>{d.pff_hits}</td><td className={td}>{d.pff_hurries}</td>
                  <td className={td}><Badge ok={d.muestra_suficiente}>{d.muestra_suficiente ? 'suficiente' : 'insuficiente'}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-slate-400">Se muestran hasta 200 filas según el orden elegido ({data.total_defensores} pass rushers en total). Tiempos solo con muestra suficiente.</p>
      </Card>
    </div>
  )
}
