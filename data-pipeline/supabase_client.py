"""
Wrapper delgado sobre supabase-py. Centraliza la conexión para que ingest.py
y train.py no dupliquen lógica de auth/retries.
"""
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_SERVICE_KEY

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
            raise RuntimeError(
                "Faltan SUPABASE_URL / SUPABASE_SERVICE_KEY en el entorno. "
                "Revisa el .env o los secrets de GitHub Actions."
            )
        _client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    return _client


def upsert_batches(table: str, rows: list[dict], on_conflict: str, batch_size: int = 500):
    """Inserta/actualiza en lotes para no exceder límites de tamaño de payload."""
    client = get_client()
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        client.table(table).upsert(batch, on_conflict=on_conflict).execute()
