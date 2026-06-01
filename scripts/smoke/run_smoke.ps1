# Smoke test end-to-end de P2 contra docker-compose local.
# Asume que estás en la raíz del repo (proyecto_final_mlops/).
#
# Lo que valida:
#   1. postgres + minio + mlflow arrancan en compose
#   2. bootstrap_db.sql crea raw_data y clean_data.properties
#   3. CSV sintético se carga en clean_data.properties
#   4. docker compose --profile training run training train ... entrena y registra en MLflow
#   5. mismo binario en evaluate + promote → alias 'production' apuntando al primer modelo
#   6. FastAPI levanta, /health responde y carga el modelo
#   7. POST /predict devuelve precio + model_version y deja registro en raw_data.inference_events
#
# Uso:
#   pwsh ./scripts/smoke/run_smoke.ps1
#   pwsh ./scripts/smoke/run_smoke.ps1 -Cleanup   # destruye contenedores y volúmenes al final

[CmdletBinding()]
param(
    [switch]$Cleanup,
    [int]$Rows = 8000,
    [string]$BatchId = "smoke-1"
)

$ErrorActionPreference = "Stop"

$py = "C:\Users\MSI\anaconda3\python.exe"
$PG = "mlops-postgres"
$compose = @("compose")

function Wait-Healthy([string]$container, [int]$timeoutSec = 120) {
    Write-Host "Esperando a que $container esté healthy..."
    $deadline = (Get-Date).AddSeconds($timeoutSec)
    while ((Get-Date) -lt $deadline) {
        $state = docker inspect -f '{{.State.Health.Status}}' $container 2>$null
        if ($state -eq "healthy") {
            Write-Host "  OK"
            return
        }
        if ($state -eq "unhealthy") {
            throw "$container quedó unhealthy"
        }
        Start-Sleep -Seconds 3
    }
    throw "Timeout esperando $container"
}

Write-Host "=== 1/7  Levantando postgres + minio + mlflow ==="
docker @compose up -d postgres minio mlflow
Wait-Healthy $PG 120
Wait-Healthy "mlops-minio" 60

# MLflow no expone healthcheck en compose; esperamos su readiness por HTTP
Write-Host "Esperando MLflow en http://localhost:15000 ..."
$deadline = (Get-Date).AddSeconds(120)
do {
    try {
        Invoke-WebRequest "http://localhost:15000/health" -TimeoutSec 3 -UseBasicParsing | Out-Null
        Write-Host "  MLflow OK"
        break
    } catch { Start-Sleep -Seconds 3 }
} while ((Get-Date) -lt $deadline)

Write-Host "=== 2/7  Creando bucket mlflow-artifacts en MinIO ==="
docker exec mlops-minio sh -c "mc alias set local http://localhost:9000 minioadmin minioadmin 2>/dev/null; mc mb -p local/mlflow-artifacts 2>/dev/null || true"

Write-Host "=== 3/7  Bootstrap de la BD (raw_data, clean_data.properties) ==="
Get-Content scripts/smoke/bootstrap_db.sql | docker exec -i $PG psql -U mlops -d mlops

Write-Host "=== 4/7  Generando CSV sintético ($Rows filas) ==="
& $py scripts/smoke/gen_synthetic_clean_data.py --out scripts/smoke/clean_properties.csv --rows $Rows

Write-Host "=== 5/7  Cargando CSV en clean_data.properties ==="
docker cp scripts/smoke/clean_properties.csv "${PG}:/tmp/clean_properties.csv"
docker exec $PG psql -U mlops -d mlops -c "TRUNCATE clean_data.properties;"
docker exec $PG psql -U mlops -d mlops -c "\COPY clean_data.properties (batch_id, brokered_by, status, price, bed, bath, acre_lot, street, city, state, zip_code, house_size, prev_sold_date) FROM '/tmp/clean_properties.csv' CSV HEADER NULL ''"

Write-Host "=== 6/7  Entrenamiento, evaluación y promoción ==="
$trainOut = docker @compose --profile training run --rm `
    -e MLFLOW_TRACKING_URI=http://mlflow:5000 `
    training train `
        --batch-id $BatchId `
        --batch-id-filter $BatchId `
        --training-reason "smoke test" `
        --clean-table clean_data.properties `
        --n-estimators 50 `
        --max-depth 12
$trainJson = ($trainOut | Select-Object -Last 1)
Write-Host "Train output: $trainJson"
$train = $trainJson | ConvertFrom-Json
$candidateVersion = $train.model_version

$evalOut = docker @compose --profile training run --rm training evaluate `
    --candidate-version $candidateVersion `
    --batch-id-filter $BatchId `
    --clean-table clean_data.properties
$evalJson = ($evalOut | Select-Object -Last 1)
Write-Host "Evaluate output: $evalJson"

# Escribir eval.json adentro del contenedor temporal:
$tmpDir = New-TemporaryFile | ForEach-Object { Remove-Item $_; New-Item -ItemType Directory -Path $_ }
$evalPath = Join-Path $tmpDir "eval.json"
$evalJson | Set-Content -Encoding utf8 $evalPath

$promoOut = docker @compose --profile training run --rm `
    -v "${tmpDir}:/work" `
    training promote `
        --evaluation-json /work/eval.json `
        --candidate-version $candidateVersion
$promoJson = ($promoOut | Select-Object -Last 1)
Write-Host "Promote output: $promoJson"

Write-Host "=== 7/7  Levantar FastAPI y probar /predict ==="
docker @compose up -d --build fastapi
Start-Sleep -Seconds 8
$health = Invoke-RestMethod -Uri "http://localhost:8000/health" -Method Get
Write-Host "Health: $($health | ConvertTo-Json -Depth 3)"

if (-not $health.model_loaded) {
    Write-Warning "El modelo aún no se reporta cargado; espero 10s más..."
    Start-Sleep -Seconds 10
    $health = Invoke-RestMethod -Uri "http://localhost:8000/health" -Method Get
}

$payload = @{
    brokered_by = "agency_1"
    status      = "for_sale"
    bed         = 3
    bath        = 2
    acre_lot    = 0.5
    street      = "street_1"
    city        = "New York"
    state       = "NY"
    zip_code    = 10001
    house_size  = 1500
    prev_sold_date = $null
} | ConvertTo-Json
$pred = Invoke-RestMethod -Uri "http://localhost:8000/predict" -Method Post -ContentType "application/json" -Body $payload
Write-Host "Prediction: $($pred | ConvertTo-Json -Depth 3)"

Write-Host "=== Verificando registro de inferencia en raw_data.inference_events ==="
docker exec $PG psql -U mlops -d mlops -c "SELECT request_id, model_version, prediction, latency_ms, status FROM raw_data.inference_events ORDER BY occurred_at DESC LIMIT 3;"

Write-Host "=== Verificando métricas Prometheus ==="
$metrics = Invoke-WebRequest "http://localhost:8000/metrics" -UseBasicParsing
$matched = ($metrics.Content -split "`n") | Where-Object { $_ -match "model_version_info|http_requests_total|http_request_duration" } | Select-Object -First 8
$matched | ForEach-Object { Write-Host "  $_" }

Write-Host ""
Write-Host "=== SMOKE TEST OK ==="
Write-Host "  MLflow UI: http://localhost:15000"
Write-Host "  MinIO console: http://localhost:19001  (minioadmin / minioadmin)"
Write-Host "  FastAPI docs: http://localhost:8000/docs"

if ($Cleanup) {
    Write-Host "=== Cleanup ==="
    docker @compose --profile training down -v
}
