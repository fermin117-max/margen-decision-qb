// Tipos alineados con las respuestas de backend/service.py. Rutas relativas sin diagonal inicial.

export type Num = number | null

export interface Stat { n: number; mediana: Num; media: Num; min: Num; max: Num }

export interface Status { state: 'idle' | 'loading' | 'ready' | 'error'; started_at: string | null; load_seconds: Num; error: string | null; plays: Num }

export interface CategoryRow { categoria: string; descripcion: string; jugadas: number; porcentaje: Num }

export interface Summary {
  total_jugadas: number
  presion_antes_del_lanzamiento: number
  presion_despues_del_lanzamiento: number
  simultaneas: number
  censuradas: number
  sin_lanzamiento: number
  sin_snap: number
  sin_pass_rushers: number
  categorias: CategoryRow[]
  suma_categorias: number
  margen_exacto: Stat & { excluye_censuradas: boolean; nota: string }
  tiempo_hasta_presion_s: Stat
  censuradas_cota_inferior_s: Stat
  tracking_tras_lanzamiento_s: Stat
  proximidad_en_snap: number
  histograma_margen_exacto: { margen_s: number; agrupado_menor_igual: boolean; jugadas: number }[]
  nota_metodologica: string
}

export interface MarginBlock {
  jugadas: number
  categorias: Record<string, number>
  margenes_exactos: number
  jugadas_censuradas: number
  pct_censuradas_sobre_elegibles: Num
  margen_exacto_mediana_s: Num
  margen_exacto_media_s: Num
  cota_inferior_censuradas_mediana_s: Num
  muestra_suficiente: boolean
}

export interface QBRow {
  nfl_id: number; nombre: string | null; equipos: string[]
  jugadas_analizadas: number; margenes_exactos: number
  presion_antes_del_lanzamiento: number; presion_despues_del_lanzamiento: number; simultaneas: number
  censuradas: number; sin_lanzamiento: number; pct_censuradas_sobre_elegibles: Num
  margen_exacto_mediana_s: Num; margen_exacto_media_s: Num; tiempo_lanzamiento_mediana_s: Num
  muestra_suficiente: boolean
}
export interface QBList { min_margenes_exactos: number; total_quarterbacks: number; con_muestra_suficiente: number; nota: string; quarterbacks: QBRow[] }

export type Group = MarginBlock & { valor: string | number | null }
export interface QBDetail {
  nfl_id: number; nombre: string | null; equipos: string[]
  resumen: MarginBlock & { tiempo_lanzamiento_s: Stat; tiempo_hasta_presion_s: Stat; min_margenes_exactos: number }
  min_margenes_exactos_desglose: number
  desgloses: Record<'formacion' | 'cobertura' | 'down' | 'distancia_por_avanzar' | 'resultado', Group[]>
}

export interface DefRow {
  nfl_id: number; nombre: string | null; posicion_oficial: string | null
  jugadas_como_pass_rusher: number; jugadas_con_snap: number
  presiones_detectadas_tracking: number; primero_en_llegar: number; tasa_presion_tracking: Num
  tiempo_hasta_presion_mediana_s: Num; tiempo_hasta_presion_media_s: Num; proximidad_en_snap: number
  pff_sacks: number; pff_hits: number; pff_hurries: number; muestra_suficiente: boolean
}
export interface DefList { min_jugadas_como_pass_rusher: number; total_defensores: number; con_muestra_suficiente: number; nota: string; defensores: DefRow[] }

export interface Play {
  gameId: number; playId: number; qb_nflId: Num; qb_nombre: string | null
  possessionTeam: string | null; defensiveTeam: string | null; quarter: Num; down: Num; yardsToGo: Num
  offenseFormation: string | null; pff_passCoverage: string | null; outcome: string | null
  snap_frame: Num; snap_event: string | null; throw_frame: Num; throw_event: string | null; last_frame: Num
  throw_time_s: Num; pressure_status: string; pressure_frame: Num; pressure_time_s: Num
  pressure_defenders: { nfl_id: number; nombre: string | null }[]; pressure_tie: boolean
  margin_category: string; margin_is_exact: boolean; decision_margin_s: Num
  observed_margin_lower_bound_s: Num; observed_after_throw_s: Num
  preexisting_proximity_at_snap: boolean; pff_hit: number; pff_hurry: number; pff_sack: number
  review_flags: string[]
}
export interface PlayPage { total: number; limit: number; offset: number; devueltas: number; categorias: Record<string, number>; margen_exacto: Stat; jugadas: Play[] }
export interface Rusher {
  nflId: number; nombre: string | null; pff_positionLinedUp: string | null; within_at_snap: boolean; arrived: boolean
  arrival_frame: Num; arrival_time_s: Num; dist_at_arrival_yd: Num; first_to_arrive: boolean
  pff_hit: number; pff_hurry: number; pff_sack: number
}
export type PlayDetail = Play & { playDescription: string | null; snap_source: string | null; throw_source: string | null; pass_rushers: Rusher[] }

export interface Opt { valor: string | number; jugadas: number; descripcion?: string | null }
export interface Filters {
  quarterbacks: { nfl_id: number; nombre: string | null; jugadas: number }[]
  defensores: { nfl_id: number; nombre: string | null; jugadas_como_pass_rusher: number }[]
  formaciones: Opt[]; coberturas: Opt[]; downs: Opt[]; distancias_por_avanzar: Opt[]
  resultados: Opt[]; categorias_margen: Opt[]
}

export type BRow = MarginBlock & { offenseFormation?: string; pff_passCoverage?: string }
export interface Breakdowns { min_margenes_exactos: number; formacion: BRow[]; cobertura: BRow[]; formacion_cobertura: BRow[]; nota: string }

export class ApiError extends Error {
  constructor(public status: number, msg: string) { super(msg) }
}

export async function api<T>(path: string, params?: Record<string, string | number | undefined | null>): Promise<T> {
  const qs = params
    ? '?' + Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join('&')
    : ''
  const r = await fetch(`api/${path}${qs === '?' ? '' : qs}`)
  if (!r.ok) {
    const msg = r.status === 503 ? 'El backend está calculando las métricas; reintentando…' : `Error HTTP ${r.status} en api/${path}`
    throw new ApiError(r.status, msg)
  }
  return r.json() as Promise<T>
}

// Etiquetas y colores de categorías (las cuatro categorías principales siempre separadas).
export const CAT: Record<string, { label: string; color: string }> = {
  pressure_before_throw: { label: 'Presión antes del lanzamiento', color: '#f87171' },
  simultaneous_pressure_and_throw: { label: 'Simultánea (mismo frame)', color: '#fbbf24' },
  pressure_after_throw: { label: 'Presión después del lanzamiento', color: '#34d399' },
  pressure_not_observed_censored: { label: 'Censurada (presión no observada)', color: '#60a5fa' },
  not_applicable_no_throw: { label: 'Sin lanzamiento', color: '#64748b' },
  not_applicable_no_snap: { label: 'Sin snap', color: '#475569' },
  not_applicable_no_qb_or_rushers: { label: 'Sin QB/pass rushers', color: '#334155' },
  not_applicable_throw_before_snap: { label: 'Lanzamiento antes del snap', color: '#1e293b' },
}
export const OUTCOME: Record<string, string> = {
  completion: 'Completo', incompletion: 'Incompleto', interception: 'Intercepción', sack: 'Sack', scramble: 'Scramble',
}
export const fmt = (v: Num | undefined, d = 2, suf = ''): string => (v === null || v === undefined ? '—' : `${v.toFixed(d)}${suf}`)
export const int = (v: number | null | undefined): string => (v === null || v === undefined ? '—' : v.toLocaleString('es-MX'))
