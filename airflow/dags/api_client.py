"""
Cliente robusto para la API de datos: cristiandiaz13/mlops-puj:data-api-pf-v1
"""
import logging
import os
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

DATA_API_HOST   = os.getenv("DATA_API_HOST",    "data-api")
DATA_API_PORT   = os.getenv("DATA_API_PORT",    "80")
DATA_API_GROUP  = int(os.getenv("DATA_API_GROUP_ID",  "1"))
API_TIMEOUT     = int(os.getenv("DATA_API_TIMEOUT",   "30"))
API_MAX_RETRIES = int(os.getenv("DATA_API_MAX_RETRIES", "3"))

BASE_URL = f"http://{DATA_API_HOST}:{DATA_API_PORT}"


def _session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=API_MAX_RETRIES,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s


def fetch_batch(batch_number: int, group_id: Optional[int] = None) -> Optional[dict]:
    """
    Solicita un lote a la API. Retorna None cuando no hay más datos.

    Returns:
        dict: {batch_id, batch_number, group_id, records, n_records, source_url}
        None: fin del dataset (204, lista vacía, flag end_of_data).
    Raises:
        RuntimeError: si todos los endpoints fallan con error no recuperable.
    """
    gid = group_id or DATA_API_GROUP
    session = _session()

    # Probar patrones de endpoint en orden hasta encontrar el correcto.
    # El primero es el que efectivamente usa cristiandiaz13/mlops-puj:data-api-pf-v1
    # (verificado contra /openapi.json del contenedor).
    candidate_urls = [
        f"{BASE_URL}/data?group_number={gid}",
        f"{BASE_URL}/data/{gid}/{batch_number}",
        f"{BASE_URL}/data?group_id={gid}&batch={batch_number}",
        f"{BASE_URL}/batch/{gid}/{batch_number}",
        f"{BASE_URL}/api/v1/data?group={gid}&batch={batch_number}",
    ]

    last_error = None
    for url in candidate_urls:
        try:
            resp = session.get(url, timeout=API_TIMEOUT)

            if resp.status_code == 404:
                continue
            if resp.status_code == 204:
                log.info("API: sin más datos (204 No Content)")
                return None
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    records = data
                elif isinstance(data, dict):
                    records = data.get("data") or data.get("records") or data.get("items") or []
                    if data.get("end_of_data") or data.get("no_more_data"):
                        log.info("API: fin de datos indicado en respuesta JSON")
                        return None
                else:
                    records = []

                if not records:
                    log.info("API: lista vacía para lote %d — fin de datos", batch_number)
                    return None

                batch_id = (
                    data.get("batch_id") if isinstance(data, dict) else None
                ) or f"batch_{gid}_{batch_number:04d}"

                log.info("Lote %s recibido: %d registros", batch_id, len(records))
                return {
                    "batch_id":     batch_id,
                    "batch_number": batch_number,
                    "group_id":     gid,
                    "records":      records,
                    "n_records":    len(records),
                    "source_url":   url,
                }
            resp.raise_for_status()
        except requests.exceptions.ConnectionError as e:
            last_error = e
            log.warning("Conexión fallida en %s: %s", url, e)
        except requests.exceptions.Timeout:
            last_error = TimeoutError(f"Timeout en {url}")
            log.warning("Timeout en %s después de %ds", url, API_TIMEOUT)
        except requests.exceptions.HTTPError as e:
            last_error = e
            log.warning("HTTP error en %s: %s", url, e)

    raise RuntimeError(
        f"No se pudo obtener el lote {batch_number} del grupo {gid} "
        f"tras probar {len(candidate_urls)} endpoints. Último error: {last_error}. "
        "Verifica que DATA_API_HOST y DATA_API_PORT apunten al contenedor correcto."
    )


def check_health() -> bool:
    """Verifica que la API esté disponible."""
    s = _session()
    for ep in ["/health", "/", "/docs"]:
        try:
            r = s.get(f"{BASE_URL}{ep}", timeout=10)
            if r.status_code < 500:
                return True
        except Exception:
            continue
    return False
