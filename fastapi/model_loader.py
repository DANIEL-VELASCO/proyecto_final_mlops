"""Carga y recarga thread-safe del modelo productivo desde MLflow.

Mecanismo (RF7):
- Carga inicial al startup.
- /reload-model fuerza recarga (endpoint protegido por token).
- Verificación periódica en background: si el alias 'production' apunta a una
  versión distinta a la cargada, la recarga sin redespliegue.
- Si la nueva carga falla, mantiene el modelo previo en memoria (fallback).
- Lock con threading.RLock para que /predict no quede en estado inconsistente
  durante la recarga (write-favored: predict toma read snapshot atómico).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Optional

import mlflow
import mlflow.pyfunc
import pandas as pd

logger = logging.getLogger("p2.fastapi.model_loader")


@dataclass
class LoadedModel:
    pyfunc: mlflow.pyfunc.PyFuncModel
    version: str
    alias: str
    loaded_at: float


class ModelLoader:
    def __init__(
        self,
        model_name: str,
        alias: str,
        tracking_uri: str,
        poll_interval_sec: int = 30,
    ) -> None:
        self.model_name = model_name
        self.alias = alias
        self.tracking_uri = tracking_uri
        self.poll_interval_sec = poll_interval_sec
        self._lock = threading.RLock()
        self._loaded: Optional[LoadedModel] = None
        self._poller: Optional[threading.Thread] = None
        self._stop = threading.Event()

        mlflow.set_tracking_uri(tracking_uri)

    def _fetch_alias_version(self) -> Optional[str]:
        client = mlflow.tracking.MlflowClient()
        try:
            mv = client.get_model_version_by_alias(self.model_name, self.alias)
            return mv.version
        except Exception as exc:
            logger.warning("Sin alias '%s' para '%s': %s", self.alias, self.model_name, exc)
            return None

    def load(self) -> Optional[LoadedModel]:
        """Carga el modelo apuntado por el alias. Si falla, conserva el previo."""
        version = self._fetch_alias_version()
        if version is None:
            logger.warning("No hay modelo productivo todavía — se esperará al primer ciclo")
            return self._loaded

        with self._lock:
            current = self._loaded
            if current is not None and current.version == version:
                logger.info("Versión productiva sin cambios (v%s)", version)
                return current

            uri = f"models:/{self.model_name}@{self.alias}"
            try:
                logger.info("Cargando modelo desde %s (v%s)", uri, version)
                model = mlflow.pyfunc.load_model(uri)
                new = LoadedModel(
                    pyfunc=model, version=version, alias=self.alias, loaded_at=time.time()
                )
                self._loaded = new
                logger.info("Modelo cargado correctamente — v%s", version)
                return new
            except Exception as exc:
                logger.error("Error cargando modelo v%s: %s — se mantiene el modelo previo", version, exc)
                return current

    def current(self) -> Optional[LoadedModel]:
        with self._lock:
            return self._loaded

    def predict(self, X: pd.DataFrame) -> tuple[float, LoadedModel]:
        """Predice y retorna (valor, snapshot del modelo usado).

        El snapshot retornado garantiza trazabilidad: si entre /predict y el log se
        recarga el modelo, registramos la versión que efectivamente atendió la petición.
        """
        snapshot = self.current()
        if snapshot is None:
            raise RuntimeError("Modelo no cargado todavía")
        y = snapshot.pyfunc.predict(X)
        if hasattr(y, "__len__"):
            value = float(y[0])
        else:
            value = float(y)
        return value, snapshot

    def start_background_poller(self) -> None:
        """Lanza un hilo que verifica el alias cada N segundos."""
        if self._poller is not None and self._poller.is_alive():
            return

        def _loop():
            logger.info("Background poller iniciado (cada %ds)", self.poll_interval_sec)
            while not self._stop.is_set():
                try:
                    self.load()
                except Exception as exc:  # pragma: no cover
                    logger.exception("Error en poller: %s", exc)
                self._stop.wait(self.poll_interval_sec)

        self._poller = threading.Thread(target=_loop, daemon=True, name="model-poller")
        self._poller.start()

    def stop_background_poller(self) -> None:
        self._stop.set()
        if self._poller is not None:
            self._poller.join(timeout=5)


def build_default_loader() -> ModelLoader:
    return ModelLoader(
        model_name=os.getenv("MLFLOW_MODEL_NAME", "house-price-model"),
        alias=os.getenv("MLFLOW_PRODUCTION_ALIAS", "production"),
        tracking_uri=os.environ["MLFLOW_TRACKING_URI"],
        poll_interval_sec=int(os.getenv("MODEL_POLL_INTERVAL_SEC", "30")),
    )
