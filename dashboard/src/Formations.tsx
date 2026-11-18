import { useMemo } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis, ReferenceLine, Legend } from 'recharts'
import { Breakdowns, BRow, fmt } from './api'
import { axis, Card, Status, td, th, tooltipStyle, useApi } from './ui'

function GroupChart({ rows, keyName, title, min }: { rows: BRow[]; keyName: 'offenseFormation' | 'pff_passCoverage'; title: string; min: number }) {
  const data = rows.map((r) => ({
    nombre: String(r[keyName]), n: r.jugadas, exactos: r.margenes_exactos,
    antes: r.categorias.pressure_before_throw, simult: r.categorias.simultaneous_pressure_and_throw,
    despues: r.categorias.pressure_after_throw, censuradas: r.jugadas_censuradas,
    media: r.muestra_suficiente ? r.margen_exacto_media_s : null,
  }))
  return (
    <Card title={title}>
      <div className="h-64">
        <ResponsiveContainer>
          <BarChart data={data}>
            <CartesianGrid stroke="#1e293b" vertical={false} />
            <XAxis dataKey="nombre" {...axis} interval={0} angle={-30} textAnchor="end" height={55} />
            <YAxis {...axis} />
            <Tooltip contentStyle={tooltipStyle} />
            <Legend wrapperStyle={{ fontSize: 11 }} verticalAlign="top" />
            <Bar stackId="a" dataKey="antes" name="Antes" fill="#f87171" />
            <Bar stackId="a" dataKey="simult" name="Simultánea" fill="#fbbf24" />
            <Bar stackId="a" dataKey="despues" name="Después" fill="#34d399" />
            <Bar stackId="a" dataKey="censuradas" name="Censuradas" fill="#60a5fa" />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-2 h-48">
        <ResponsiveContainer>
          <BarChart data={data.filter((d) => d.media !== null)}>
            <CartesianGrid stroke="#1e293b" vertical={false} />
            <XAxis dataKey="nombre" {...axis} interval={0} angle={-30} textAnchor="end" height={55} />
            <YAxis {...axis} unit=" s" />
            <ReferenceLine y={0} stroke="#fbbf24" />
            <Tooltip contentStyle={tooltipStyle} formatter={(v: unknown) => [`${Number(v).toFixed(2)} s`, 'Margen exacto medio']}
              labelFormatter={(l: unknown, p: readonly { payload?: { exactos?: number } }[]) => `${String(l)} · n = ${p?.[0]?.payload?.exactos ?? '—'} márgenes exactos`} />
            <Bar dataKey="media" name="Margen exacto medio">
              {data.filter((d) => d.media !== null).map((d) => <Cell key={d.nombre} fill={(d.media ?? 0) < 0 ? '#f87171' : '#34d399'} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="text-xs text-slate-400">Arriba: jugadas por categoría (todas las jugadas del grupo). Abajo: margen exacto medio, solo grupos con ≥ {min} márgenes exactos.</p>
    </Card>
  )
}

export default function Formations() {
  const { data, error, loading } = useApi<Breakdowns>('breakdowns')
  const combos = useMemo(() => (data?.formacion_cobertura ?? []).filter((r) => r.muestra_suficiente)
    .sort((a, b) => (b.margen_exacto_media_s ?? -99) - (a.margen_exacto_media_s ?? -99)), [data])
  if (!data) return <Status loading={loading} error={error} />
  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-2">
        <GroupChart rows={data.formacion} keyName="offenseFormation" title="Por formación ofensiva" min={data.min_margenes_exactos} />
        <GroupChart rows={data.cobertura} keyName="pff_passCoverage" title="Por cobertura defensiva" min={data.min_margenes_exactos} />
      </div>
      <Card title="Formación × cobertura (ordenado por margen exacto medio)" right={<span className="text-xs text-slate-400">{combos.length} combinaciones con ≥ {data.min_margenes_exactos} márgenes exactos</span>}>
        <div className="max-h-96 overflow-auto">
          <table className="w-full">
            <thead className="sticky top-0 bg-slate-900"><tr><th className={th}>Formación</th><th className={th}>Cobertura</th><th className={th}>Jugadas</th><th className={th}>Márg. exactos</th><th className={th}>Censuradas</th><th className={th}>% censur.</th><th className={th}>Media (s)</th><th className={th}>Mediana (s)</th></tr></thead>
            <tbody>
              {combos.map((r) => (
                <tr key={`${r.offenseFormation}-${r.pff_passCoverage}`} className="border-t border-slate-800">
                  <td className={td}>{r.offenseFormation}</td><td className={td}>{r.pff_passCoverage}</td><td className={td}>{r.jugadas}</td>
                  <td className={td}>{r.margenes_exactos}</td><td className={td}>{r.jugadas_censuradas}</td><td className={td}>{fmt(r.pct_censuradas_sobre_elegibles, 1, ' %')}</td>
                  <td className={`${td} ${(r.margen_exacto_media_s ?? 0) < 0 ? 'text-red-300' : 'text-emerald-300'}`}>{fmt(r.margen_exacto_media_s, 2)}</td><td className={td}>{fmt(r.margen_exacto_mediana_s, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-slate-400">{data.nota}</p>
      </Card>
    </div>
  )
}
