# Predictor de partidas Tier 1 de Dota 2 (solo por composición de héroes)

Predice la probabilidad de victoria de Radiant/Dire a partir de los 10 héroes
elegidos, entrenado únicamente con partidas de torneos profesionales **tier 1**
(`premium` + `professional` en la taxonomía de OpenDota).

## Arquitectura

```
data-pipeline/  (Python)          Recolecta datos de OpenDota, entrena los
                                   modelos y publica el activo en Supabase.
        │
        ▼
Supabase                          Postgres (partidas, drafts, registro de
(DB + Storage)                    modelos) + Storage (pesos .onnx).
        │
        ▼
web/  (Next.js, Vercel)           API /api/predict (inferencia ONNX) +
                                   interfaz de "sala de draft".

.github/workflows/pipeline.yml    Cron semanal: ingesta + reentrenamiento +
                                   promoción automática del modelo si mejora.
```

El entrenamiento **no corre en Vercel** a propósito: las funciones serverless
de Vercel no están pensadas para cargas de PyTorch/LightGBM (límites de
tiempo/memoria, sin estado persistente). Por eso el entrenamiento vive en
GitHub Actions (gratis, sin límite de memoria razonable para este dataset) y
Vercel solo hace inferencia liviana sobre un modelo ya exportado a ONNX.

## Decisiones de diseño (resumen de lo acordado)

| Tema | Decisión | Por qué |
|---|---|---|
| Bans | Se guardan en `match_draft` pero el modelo de producción usa solo picks | El input del usuario final son 10 héroes; los bans quedan disponibles para una variante futura del modelo o para analítica |
| Roles/lanes | Tabla derivada `hero_meta_by_patch`, recalculada en cada reentrenamiento | Los roles cambian de parche a parche; hardcodearlos se vuelve incorrecto con el tiempo |
| Ventana de datos | Desde el parche **7.33** (jun. 2023), con peso extra a partidas recientes (`RECENCY_HALF_LIFE_PATCHES`) | El parche 7.41 (mar. 2026) eliminó las Facetas — cortar los datos justo ahí deja muy pocas partidas tier 1 para entrenar bien. 7.33 es la última reestructuración mayor de mapa/jugabilidad anterior a ese ciclo |
| Modelo | Red neuronal con embeddings de héroe (probabilidad) + baseline LightGBM (control de calidad e interpretabilidad) | La probabilidad sale directo de la red; el binario es solo un umbral sobre esa probabilidad |
| Tier | Solo `premium` + `professional` | Evita mezclar el nivel de decisión de tier 1 con tier 2/amateur |
| Reentrenamiento | Automático semanal vía GitHub Actions, con promoción condicionada a mejorar `log_loss` de validación | Evita que un reentrenamiento con datos ruidosos degrade lo que sirve la API |

## Puesta en marcha

### 1. Supabase
1. Crea un proyecto en [supabase.com](https://supabase.com).
2. Corre la migración: `supabase/migrations/0001_init.sql` (SQL Editor o `supabase db push`).
3. Crea un bucket de Storage llamado `models` (privado).
4. Activa Row Level Security en `heroes` y `hero_meta_by_patch` con una policy
   de `SELECT` para el rol `anon` (son las únicas tablas que el navegador lee
   directamente). Todo lo demás debe quedar cerrado a `anon`.

### 2. Pipeline de datos
```bash
cd data-pipeline
cp .env.example .env        # completar SUPABASE_URL y SUPABASE_SERVICE_KEY
pip install -r requirements.txt --break-system-packages
python ingest.py            # primera carga (puede tardar según el volumen)
python train.py             # entrena NN + GBM, guarda en ./models/<version>/
python export_onnx.py --run-dir ./models/<version>   # publica el modelo activo
```

### 3. GitHub Actions (automatización)
En el repo, agrega estos secrets: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`,
`OPENDOTA_API_KEY` (opcional). El workflow `pipeline.yml` ya queda corriendo
cada lunes; también se puede disparar manualmente desde la pestaña Actions.

### 4. Web (Vercel)
```bash
cd web
cp .env.example .env.local  # completar las 4 variables
npm install
npm run dev                 # http://localhost:3000
```
Para desplegar: conecta el repo en Vercel, selecciona `web/` como root
directory del proyecto, y define las mismas variables de entorno en el
dashboard de Vercel (Production + Preview).

## Limitaciones conocidas / próximos pasos

- **Volumen de datos real**: no pude ejecutar `ingest.py` desde este entorno
  (sandbox sin acceso a `api.opendota.com`), así que el pipeline no viene
  con datos precargados ni con un modelo ya entrenado. Los tres comandos de
  la sección anterior sí quedan listos para correr en tu máquina o en CI.
- **Nombres de columnas de OpenDota Explorer** (`opendota_client.py`): están
  basados en el esquema público documentado, pero OpenDota lo ajusta de vez
  en cuando. Si `explorer_query` devuelve columnas distintas, revisa el
  esquema actual desde la propia UI en opendota.com/explorer antes de correr
  la ingesta masiva.
- **Fase 2 (pendiente de construir)**: predicción de kills por héroe y stats
  por pro-player. El esquema (`match_player_stats`) ya está listo para
  soportarlo; falta el script de entrenamiento específico (sería un modelo
  de regresión aparte, reusando el mismo dataset).
- **Bucket `models` privado**: la app web accede a él con la service key
  desde el servidor, nunca desde el navegador — así se mantiene privado.
