# -*- coding: utf-8 -*-
import pandas as pd
import numpy as np
import pvlib
import time

EXCEL_FILE = 'Sevilla_horario_2024-2026_UTC_modificado.xlsx'
LAT, LON, ALT = 37.39, -5.99, 9

def log(msg):
    print(f"[{pd.Timestamp.now().strftime('%H:%M:%S')}] {msg}")

# -------------------------------------------------------
# CARGAR DATOS
# -------------------------------------------------------
log("Cargando Excel...")
df = pd.read_excel(EXCEL_FILE, header=0, skiprows=[1])
df.columns = [str(c).strip() for c in df.columns]

print(f"✅ Columnas encontradas ({len(df.columns)}):")
for c in df.columns:
    print(f"   '{c}'")

col_time = df.columns[0]
df[col_time] = pd.to_datetime(df[col_time], dayfirst=True, errors='coerce')
df = df.dropna(subset=[col_time])
df = df.rename(columns={col_time: 'time'})
df = df.set_index('time').sort_index()

print(f"\n✅ {len(df):,} filas | {df.index.min()} → {df.index.max()}")

df_before = df.copy()

# -------------------------------------------------------
# MAPEO DE VARIABLES
# -------------------------------------------------------
def find_col(df, keywords):
    for col in df.columns:
        col_l = str(col).lower()
        if all(k.lower() in col_l for k in keywords):
            return col
    return None

cols_map = {
    'Dry-bulb':  find_col(df, ['dry']),
    'Dew Point': find_col(df, ['dew']),
    'RH':        find_col(df, ['humidity']),
    'WindDir':   find_col(df, ['direction']),
    'WindSpeed': find_col(df, ['speed']),
    'Pressure':  find_col(df, ['pressure']),
    'GHI':       find_col(df, ['global']),
    'BHI':       find_col(df, ['beam', 'horiz']),
    'DHI':       find_col(df, ['diffuse']),
    'BNI':       find_col(df, ['normal']),
}

print("\n🔍 Mapeo de variables:")
for k, v in cols_map.items():
    print(f"   {k:12} → '{v}'")

rename_dict = {v: k for k, v in cols_map.items() if v is not None}
df = df.rename(columns=rename_dict)
df_before = df_before.rename(columns=rename_dict)
cols_trabajo = [k for k, v in cols_map.items() if v is not None]

# -------------------------------------------------------
# DISPONIBILIDAD ANTES
# -------------------------------------------------------
print("\n📊 DISPONIBILIDAD ANTES DEL RELLENO:")
print("="*45)
antes = {}
for col in cols_trabajo:
    pct = df[col].notna().mean() * 100
    antes[col] = pct
    print(f"  {col:12}: {pct:6.1f}%")

input("\n▶ Presiona Enter para iniciar el relleno...")

# -------------------------------------------------------
# REINDEXAR A HORAS COMPLETAS
# -------------------------------------------------------
log("Reindexando a horas completas...")
full_index = pd.date_range(df.index.min(), df.index.max(), freq='h')
df = df.reindex(full_index)
df_before = df_before.reindex(full_index)
df.index.name = 'time'
df_before.index.name = 'time'
log(f"Horas totales esperadas: {len(full_index):,}")

# -------------------------------------------------------
# FUNCIONES AUXILIARES
# -------------------------------------------------------
def gap_size(series):
    is_nan = series.isna()
    gap_id = (~is_nan).cumsum()
    return is_nan.groupby(gap_id).transform('sum').where(is_nan, 0)

def spline_limit(series, max_gap):
    s = series.copy()
    gaps = gap_size(s)
    mask_gap = (gaps > 0) & (gaps <= max_gap)
    if not mask_gap.any():
        return s
    s_spline = s.interpolate(method='spline', order=3, limit=max_gap, limit_direction='both')
    s.loc[mask_gap] = s_spline.loc[mask_gap]
    return s

def gaps_interpolated(original, filled, var_name):
    s0 = original[var_name]
    s1 = filled[var_name]
    mask = s0.isna() & s1.notna()
    out = []
    if not mask.any(): return out
    is_gap = mask.to_numpy()
    idx = filled.index.to_numpy()
    n = len(filled)
    i = 0
    while i < n:
        if is_gap[i]:
            j = i
            while j < n and is_gap[j]: j += 1
            out.append({'Variable': var_name, 'Gap start': idx[i], 'Gap end': idx[j-1], 'Hours interpolated': j - i})
            i = j
        else:
            i += 1
    return out

# NUEVA ESTADÍSTICA COMPLETÍSIMA DE RELLENOS
def calculate_annual_stats(df_before, df, cols_trabajo):
    stats_list = []
    for col in cols_trabajo:
        if col not in df_before.columns: continue
        
        s_before = df_before[col]
        s_after = df[col]
        
        is_nan_before = s_before.isna()
        if not is_nan_before.any(): continue
        
        gap_id = (~is_nan_before).cumsum()
        df_nans = pd.DataFrame({
            'time': s_before[is_nan_before].index,
            'gap_id': gap_id[is_nan_before].values,
            'is_nan_after': s_after[is_nan_before].isna().values
        })
        
        gap_agg = df_nans.groupby('gap_id').agg(
            start_time=('time', 'first'),
            size_before=('time', 'count'),
            nans_after=('is_nan_after', 'sum')
        )
        
        gap_agg['year'] = gap_agg['start_time'].dt.year
        
        def classify_gap(row):
            if row['nans_after'] == 0: return 'Completos'
            elif row['nans_after'] == row['size_before']: return 'No rellenado'
            else: return 'Parciales'
            
        gap_agg['estado'] = gap_agg.apply(classify_gap, axis=1)
        
        for year, group in gap_agg.groupby('year'):
            total_huecos = len(group)
            rellenados = len(group[group['estado'] == 'Completos'])
            no_rellenados = len(group[group['estado'] == 'No rellenado'])
            parciales = len(group[group['estado'] == 'Parciales'])
            
            horas_originales = group['size_before'].sum()
            horas_quedan = group['nans_after'].sum()
            horas_rellenadas = horas_originales - horas_quedan
            
            stats_list.append({
                'year': year,
                'Variable': col,
                'Total_Huecos': total_huecos,
                'Rellenados_100%': rellenados,
                'Parciales': parciales,
                'No_Rellenados': no_rellenados,
                'Horas_Orig_Faltan': horas_originales,
                'Horas_Rellenadas': horas_rellenadas,
                'Horas_Siguen_Vacias': horas_quedan
            })
            
    df_stats = pd.DataFrame(stats_list)
    if df_stats.empty: return df_stats
    
    df_stats = df_stats.set_index(['year', 'Variable'])
    df_stats['Días_año'] = [366 if (y%4==0 and (y%100!=0 or y%400==0)) else 365 for y in df_stats.index.get_level_values(0)]
    df_stats['Promedio_h_relleno/día'] = (df_stats['Horas_Rellenadas'] / df_stats['Días_año']).round(2)
    
    return df_stats

# HUECOS MÁXIMOS CORREGIDO
def gaps_stats_periodos(df_before, cols_trabajo):
    max_gaps = []
    limites_interpolacion = {'Pressure': 72, 'Dry-bulb': 24, 'Dew Point': 24, 'RH': 24, 
                             'WindSpeed': 3, 'WindDir': 2, 'GHI': 24, 'BHI': 24, 'DHI': 24, 'BNI': 24}

    for col in cols_trabajo:
        if col not in df_before.columns: continue
        s = df_before[col]
        is_nan = s.isna()
        
        gap_id = (~is_nan).cumsum()[is_nan]
        if gap_id.empty: continue
        
        gap_sizes = gap_id.value_counts().sort_index()
        gap_starts = s[is_nan].reset_index().groupby(gap_id.values).first()['time']
        gap_ends = s[is_nan].reset_index().groupby(gap_id.values).last()['time']
        
        gaps_info = pd.DataFrame({'size': gap_sizes.values, 'start': gap_starts.values, 'end': gap_ends.values})
        gaps_info['year'] = gaps_info['start'].dt.year
        gaps_info['month'] = gaps_info['start'].dt.month
        limite = limites_interpolacion.get(col, 0)
        
        for y, group in gaps_info.groupby('year'):
            idx_max = group['size'].idxmax()
            row = group.loc[idx_max]
            tamano = int(row['size'])
            estado = "RELLENADO" if tamano <= limite else f"NO RELLENADO (>{limite}h)"
            max_gaps.append({'Variable': col, 'Tipo': 'AÑO', 'Periodo': y, 'Max_hueco_horas': tamano, 'Inicio': row['start'], 'Fin': row['end'], 'Estado_Relleno': estado})
            
        for m, group in gaps_info.groupby('month'):
            idx_max = group['size'].idxmax()
            row = group.loc[idx_max]
            tamano = int(row['size'])
            estado = "RELLENADO" if tamano <= limite else f"NO RELLENADO (>{limite}h)"
            max_gaps.append({'Variable': col, 'Tipo': 'MES', 'Periodo': m, 'Max_hueco_horas': tamano, 'Inicio': row['start'], 'Fin': row['end'], 'Estado_Relleno': estado})

    return pd.DataFrame(max_gaps)

# -------------------------------------------------------
# RELLENO
# -------------------------------------------------------
t0 = time.time()
log("[1/5] Rellenando Pressure (lineal ≤72h)...")
if 'Pressure' in df.columns:
    df['Pressure'] = df['Pressure'].interpolate(method='linear', limit=72)
log(f"   Hecho en {time.time()-t0:5.1f}s")

t0 = time.time()
log("[2/5] Dry-bulb y Dew Point → spline cúbico (≤24h)")
for col in ['Dry-bulb', 'Dew Point']:
    if col in df.columns:
        df[col] = spline_limit(df[col], max_gap=24)
log(f"   Hecho en {time.time()-t0:5.1f}s")

t0 = time.time()
log("[3/5] RH → psicrometría + lineal ≤24h")
if 'RH' in df.columns and 'Dry-bulb' in df.columns and 'Dew Point' in df.columns:
    mask = df['RH'].isna() & df['Dry-bulb'].notna() & df['Dew Point'].notna()
    T  = df.loc[mask, 'Dry-bulb']
    Td = df.loc[mask, 'Dew Point']
    df.loc[mask, 'RH'] = (100 * np.exp(17.625*Td/(243.04+Td)) / np.exp(17.625*T/(243.04+T))).clip(0, 100)
    df['RH'] = df['RH'].interpolate(method='linear', limit=24)
log(f"   Hecho en {time.time()-t0:5.1f}s")

t0 = time.time()
log("[4/5] WindSpeed ≤3h, WindDir ≤2h")
if 'WindSpeed' in df.columns:
    df['WindSpeed'] = df['WindSpeed'].interpolate(method='linear', limit=3)
if 'WindDir' in df.columns:
    df['WindDir']   = df['WindDir'].interpolate(method='linear', limit=2)
log(f"   Hecho en {time.time()-t0:5.1f}s")

t0 = time.time()
log("[5/5] GHI, DHI, BNI, BHI → pvlib")
location = pvlib.location.Location(LAT, LON, tz='UTC', altitude=ALT)
times_utc = df.index.tz_localize('UTC') if df.index.tz is None else df.index
cs  = location.get_clearsky(times_utc)
GHIc = pd.Series(cs['ghi'].values, index=df.index)
DHIc = pd.Series(cs['dhi'].values, index=df.index)
BNIc = pd.Series(cs['dni'].values, index=df.index)
es_dia = GHIc > 5

for col, ref in [('GHI', GHIc), ('DHI', DHIc), ('BNI', BNIc)]:
    if col not in df.columns: continue
    df[col] = df[col].interpolate(method='linear', limit=3)
    mask_medio = gap_size(df[col]).between(3, 24) & es_dia
    if mask_medio.any():
        kt = (df[col] / ref.replace(0, np.nan)).clip(0, 1.2)
        kt_med = kt.rolling(24, min_periods=6, center=True).median()
        df.loc[mask_medio, col] = (ref[mask_medio] * kt_med[mask_medio]).clip(0)
    df.loc[~es_dia, col] = df.loc[~es_dia, col].fillna(0)

if {'GHI', 'DHI'}.issubset(df.columns):
    df['BHI'] = (df['GHI'] - df['DHI']).clip(lower=0)
log(f"   Hecho en {time.time()-t0:5.1f}s")

# -------------------------------------------------------
# TABLA DE INTERVALOS INTERPOLADOS
# -------------------------------------------------------
log("Construyendo tabla de intervalos...")
records = []
for col in cols_trabajo:
    if col in df.columns and col in df_before.columns:
        records.extend(gaps_interpolated(df_before, df, col))
gaps_df = pd.DataFrame(records)

# -------------------------------------------------------
# ESTADÍSTICAS AVANZADAS (AÑADIDAS NUEVAS MÉTRICAS)
# -------------------------------------------------------
log("Calculando estadísticas avanzadas (rellenados vs no rellenados)...")
stats_anuales = calculate_annual_stats(df_before, df, cols_trabajo)

print("\n" + "="*100)
print("📈 ESTADÍSTICAS POR AÑO Y VARIABLE")
print("="*100)
if not stats_anuales.empty:
    print(stats_anuales.to_string())

log("Buscando max huecos por AÑO y MES...")
max_gaps_df = gaps_stats_periodos(df_before, cols_trabajo)

print("\n" + "="*80)
print("⏳ HUECO MÁS LARGO POR AÑO Y MES")
print("="*80)
if not max_gaps_df.empty:
    print(max_gaps_df.groupby(['Tipo', 'Periodo', 'Variable']).agg({
        'Max_hueco_horas': 'max', 
        'Estado_Relleno': 'first'
    }).reset_index().to_string(index=False))
    print("\n📊 TOP 10 HUECOS MÁS GRANDES:")
    print(max_gaps_df.nlargest(10, 'Max_hueco_horas')[['Variable', 'Tipo', 'Periodo', 'Max_hueco_horas', 'Inicio', 'Estado_Relleno']].to_string(index=False))

# -------------------------------------------------------
# COMPARATIVA ANTES / DESPUÉS
# -------------------------------------------------------
print("\n📊 COMPARATIVA ANTES vs DESPUÉS:")
print(f"  {'Variable':12} {'Antes':>8} {'Después':>8} {'Ganancia':>9}")
print("="*45)
despues = {}
for col in cols_trabajo:
    d = df[col].notna().mean() * 100
    despues[col] = d
    a = antes.get(col, 0)
    print(f"  {col:12} {a:7.1f}% {d:7.1f}% {d-a:+8.1f}%")

summary = pd.DataFrame({
    'Variable': cols_trabajo,
    'Before_%': [antes[c] for c in cols_trabajo],
    'After_%':  [despues[c] for c in cols_trabajo],
    'Gain_%':   [despues[c] - antes[c] for c in cols_trabajo]
})

# -------------------------------------------------------
# GUARDAR EXCELS
# -------------------------------------------------------
log("Guardando Excels...")
df[cols_trabajo].reset_index().to_excel('Sevilla_RELLENADO.xlsx', index=False)

OUTPUT = 'Sevilla_RELLENADO_con_gaps.xlsx'
with pd.ExcelWriter(OUTPUT, engine='openpyxl') as writer:
    df[cols_trabajo].reset_index().to_excel(writer, sheet_name='rellenado', index=False)
    summary.to_excel(writer, sheet_name='summary', index=False)
    gaps_df.to_excel(writer, sheet_name='gaps', index=False)
    if not stats_anuales.empty:
        stats_anuales.to_excel(writer, sheet_name='stats_anuales')
    if not max_gaps_df.empty:
        max_gaps_df.to_excel(writer, sheet_name='max_gaps', index=False)

with pd.ExcelWriter('ESTADISTICAS_ANUALES.xlsx', engine='openpyxl') as writer:
    if not stats_anuales.empty:
        stats_anuales.to_excel(writer, sheet_name='stats_anuales')
    if not max_gaps_df.empty:
        max_gaps_df.to_excel(writer, sheet_name='max_gaps', index=False)

print(f"\n💾 Guardados:")
print("   - Sevilla_RELLENADO.xlsx")
print(f"   - {OUTPUT}")
print("   - ESTADISTICAS_ANUALES.xlsx")

log("Proceso COMPLETADO ✓")