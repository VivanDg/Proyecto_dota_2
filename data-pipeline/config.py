"""
Configuración centralizada. Todo se lee de variables de entorno para poder
correr esto tanto localmente (.env) como en GitHub Actions (secrets).
"""
import os
from dotenv import load_dotenv

load_dotenv()

# --- Supabase ---
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
# Usar la service_role key (no la anon key) porque este pipeline escribe datos.
# NUNCA exponer esta key en el frontend.
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

# --- OpenDota ---
OPENDOTA_BASE_URL = "https://api.opendota.com/api"
OPENDOTA_API_KEY = os.environ.get("OPENDOTA_API_KEY", "")  # opcional, sube el rate limit

# --- Ventana de datos (ver justificación en README) ---
# Ancla: parche 7.33 (jun 2023) fue la última actualización mayor de mapa/jugabilidad
# antes del ciclo de Facetas. Se usa como piso de la ventana de entrenamiento.
MIN_PATCH_NUMBER = os.environ.get("MIN_PATCH_NUMBER", "7.33")

# Solo torneos tier 1. OpenDota usa 'premium' para majors/TI y 'professional'
# para el resto del circuito profesional reconocido.
VALID_TIERS = ["premium", "professional"]

# Peso extra que se le da a las partidas del parche más reciente al entrenar
# (recency weighting). 1.0 = sin peso extra, valores > 1 priorizan lo reciente.
RECENCY_HALF_LIFE_PATCHES = float(os.environ.get("RECENCY_HALF_LIFE_PATCHES", "3"))

# --- Paths locales ---
DATA_DIR = os.environ.get("DATA_DIR", "./data")
MODEL_DIR = os.environ.get("MODEL_DIR", "./models")
