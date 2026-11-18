import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis, ReferenceLine } from 'recharts'
import { CAT, fmt, int, Summary } from './api'
import { axis, Card, Kpi, tooltipStyle } from './ui'

export default function Overview({ s }: { s: Summary }) {
  const cats = s.categorias.map((c) => ({ ...c, label: CAT[c.categoria]?.label ?? c.categoria, color: CAT[c.categoria]?.color ?? '#64748b' }))
    .filter((c) => c.jugadas > 0)
  const hist = s.histograma_margen_exacto.map((h) => ({ ...h, x: h.agrupado_menor_igual ? '≤-3.0' : h.margen_s.toFixed(1) }))
  const me = s.margen_exacto
  const tp = s.tiempo_hasta_presion_s
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Total de jugadas" value={int(s.total_jugadas)} sub={`${int(s.suma_categorias)} clasificadas en categorías`} accent="text-slate-100" />
        <Kpi label="Márgenes exactos" value={int(me.n)} sub="antes + simultánea + después" accent="text-sky-400" />
        <Kpi label="Presión antes del lanzamiento" value={int(s.presion_antes_del_lanzamiento)} sub="margen < 0" accent="text-red-400" />
        <Kpi label="Presión después del lanzamiento" value={int(s.presion_despues_del_lanzamiento)} sub="margen > 0 (máx. ~0.4 s observable)" accent="text-emerald-400" />
        <Kpi label="Simultáneas" value={int(s.simultaneas)} sub="mismo frame, margen = 0" accent="text-amber-300" />
        <Kpi label="Censuradas" value={int(s.censuradas)} sub={`presión no observada · cota inferior mediana ${fmt(s.censuradas_cota_inferior_s.mediana, 1, ' s')}`} accent="text-blue-400" />
        <Kpi label="Tiempo mediano a la presión" value={fmt(tp.mediana, 1, ' s')} sub={`media ${fmt(tp.media, 2, ' s')} · n = ${int(tp.n)}`} accent="text-emerald-400" />
        <Kpi label="Margen exacto medio" value={fmt(me.media, 2, ' s')} sub={`mediana ${fmt(me.mediana, 1, ' s')} · n = ${int(me.n)} (sin censuradas)`} accent="text-sky-400" />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Distribución de categorías" right={<span className="text-xs text-slate-400">n = {int(s.total_jugadas)}</span>}>
          <div className="h-72">
            <ResponsiveContainer>
              <BarChart data={cats} layout="vertical" margin={{ left: 10, right: 50 }}>
                <CartesianGrid stroke="#1e293b" horizontal={false} />
                <XAxis type="number" {...axis} />
                <YAxis type="category" dataKey="label" width={190} {...axis} />
                <Tooltip contentStyle={tooltipStyle} formatter={(v: unknown, _n: unknown, p: { payload?: { porcentaje?: number } }) => [`${int(Number(v))} jugadas (${p.payload?.porcentaje ?? '—'} %)`, 'Jugadas']} />
                <Bar dataKey="jugadas" label={{ position: 'right', fill: '#cbd5e1', fontSize: 11, formatter: (v: unknown) => int(Number(v)) }}>
                  {cats.map((c) => <Cell key={c.categoria} fill={c.color} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-1 text-xs text-slate-400">
            {cats.map((c) => <div key={c.categoria}><span className="mr-1 inline-block h-2 w-2 rounded-sm" style={{ background: c.color }} />{c.label}: {c.porcentaje} %</div>)}
          </div>
        </Card>

        <Card title="Distribución del margen exacto (s)" right={<span className="text-xs text-slate-400">n = {int(me.n)} · excluye {int(s.censuradas)} censuradas</span>}>
          <div className="h-72">
            <ResponsiveContainer>
              <BarChart data={hist} margin={{ right: 10 }}>
                <CartesianGrid stroke="#1e293b" vertical={false} />
                <XAxis dataKey="x" {...axis} interval={2} />
                <YAxis {...axis} />
                <ReferenceLine x="0.0" stroke="#fbbf24" strokeDasharray="4 4" />
                <Tooltip contentStyle={tooltipStyle} formatter={(v: unknown) => [`${int(Number(v))} jugadas`, 'Jugadas']} labelFormatter={(l: unknown) => `Margen ${String(l)} s`} />
                <Bar dataKey="jugadas">
                  {hist.map((h) => <Cell key={h.x} fill={h.margen_s < 0 ? '#f87171' : h.margen_s === 0 ? '#fbbf24' : '#34d399'} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-2 text-xs text-slate-400">Resolución de 0.1 s (10 FPS). Los márgenes positivos se truncan en ~0.4 s porque el tracking termina ~0.5 s después del lanzamiento.</p>
        </Card>
      </div>

      <Card title="¿Cómo se lee el margen?">
        <div className="grid gap-3 md:grid-cols-4">
          {[
            ['Margen < 0', 'La presión llegó antes del lanzamiento.', 'border-red-500/60 text-red-300'],
            ['Margen = 0', 'Presión y lanzamiento en el mismo frame (0.1 s).', 'border-amber-400/60 text-amber-200'],
            ['Margen > 0', 'La presión se detectó después del lanzamiento. No mide todo el tiempo libre del QB.', 'border-emerald-500/60 text-emerald-300'],
            ['Censurada', 'El tracking terminó sin detectar presión. No significa que nunca hubo presión: solo hay una cota inferior.', 'border-blue-500/60 text-blue-300'],
          ].map(([t, d, c]) => (
            <div key={t} className={`rounded-lg border-l-4 bg-slate-950/60 p-3 ${c}`}>
              <div className="font-semibold">{t}</div>
              <div className="mt-1 text-sm text-slate-300">{d}</div>
            </div>
          ))}
        </div>
        <p className="mt-3 text-sm text-slate-300">
          <b>Margen de decisión</b> = tiempo hasta la presión − tiempo de lanzamiento, ambos medidos desde el snap.
        </p>
      </Card>
    </div>
  )
}
