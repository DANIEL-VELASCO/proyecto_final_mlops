#!/usr/bin/env bash
# Entrypoint multi-comando para que el DAG (P1) pueda invocar:
#   docker run mlops-training train    --batch-id X --training-reason "..."
#   docker run mlops-training evaluate --candidate-version 3
#   docker run mlops-training promote  --evaluation-json /tmp/eval.json --candidate-version 3
set -euo pipefail

cmd="${1:-help}"
shift || true

case "$cmd" in
  train)
    exec python -u train.py "$@"
    ;;
  evaluate)
    exec python -u evaluate.py "$@"
    ;;
  promote)
    exec python -u promote.py "$@"
    ;;
  help|--help|-h|"")
    echo "Uso: <train|evaluate|promote> [args]"
    echo ""
    echo "  train    â€” entrena candidato y lo registra en MLflow"
    echo "  evaluate â€” evalÃºa candidato vs. modelo productivo"
    echo "  promote  â€” aplica regla de promociÃ³n y actualiza alias en MLflow"
    exit 0
    ;;
  *)
    echo "Comando desconocido: $cmd" >&2
    exit 2
    ;;
esac
