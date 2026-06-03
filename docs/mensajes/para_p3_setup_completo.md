# 🚀 Setup del proyecto en tu PC desde cero — para P3 (Daniel)

> Esta guía levanta el sistema completo en **tu máquina** desde un git clone
> limpio. Está validada al 2026-06-03 con la última versión de `main`
> (commit `e2b9aa2`). Tiempo total: ~30-45 min si todo va bien.

---

## 0. Pre-requisitos en tu PC

| Requisito | Comando para verificar | Qué hacer si falta |
|---|---|---|
| Windows 10/11 con 16 GB RAM | — | — |
| Docker Desktop instalado | `docker version` | Instalar desde docker.com |
| Kubernetes habilitado en Docker Desktop | `kubectl cluster-info` | Docker Desktop → Settings → Kubernetes → ☑️ Enable Kubernetes → Apply |
| Git | `git --version` | Instalar Git for Windows |
| `kubectl` | `kubectl version --client` | Viene con Docker Desktop |
| PowerShell 5+ | `$PSVersionTable.PSVersion` | Nativo de Windows |

### 0.1 Configurar WSL2 con RAM suficiente

El clúster + entrenamiento consumen ~7 GB. Si Docker Desktop está limitado a 4 GB,
te va a tirar OOMKilled cada 2 minutos.

Crear el archivo `C:\Users\<tu_usuario>\.wslconfig` con este contenido:

```ini
[wsl2]
memory=8GB
processors=4
swap=4GB
```

> Si tu PC tiene 32 GB de RAM, puedes subir a `memory=12GB`.
> Si solo tienes 16 GB, **no subas más de 8 GB** — Windows se ahoga.

Después aplica el cambio:

```powershell
wsl --shutdown
# espera 10 segundos
# luego: click derecho en Docker Desktop → Quit Docker Desktop → reabrir
```

Verifica el cambio en Docker Desktop → Settings → Resources → Advanced → debe decir ~8 GB.

---

## 1. Clonar el repositorio

```powershell
cd C:\Users\<tu_usuario>\Documents
git clone https://github.com/DANIEL-VELASCO/proyecto_final_mlops.git
cd proyecto_final_mlops
```

---

## 2. Construir las 2 imágenes locales

⚠️ **Esto es crítico**: los manifiestos de Airflow y Streamlit apuntan a
`danielvelasco01/mlops-airflow:latest` y `danielvelasco01/mlops-streamlit:latest`.
Estas imágenes **NO están publicadas en DockerHub** — son tags locales.
Si las saltas, los pods van a quedar en `ImagePullBackOff`.

Las imágenes de FastAPI y Training (`max181818/mlops-fastapi`, `max181818/mlops-training`)
**SÍ están publicadas en DockerHub**, las pullea solo.

```powershell
docker build -t danielvelasco01/mlops-airflow:latest .\airflow
docker build -t danielvelasco01/mlops-streamlit:latest .\streamlit
```

Cada build toma ~3-5 min. Verifica al final:

```powershell
docker images | Select-String "danielvelasco01|max181818"
# Esperado: 4 imágenes listadas
```

---

## 3. Aplicar manifiestos de Kubernetes

### 3.1 Namespace + Secrets

```powershell
kubectl apply -f kubernetes\namespace.yaml
kubectl apply -f kubernetes\secrets.yaml
```

### 3.2 Bases de datos (Postgres con init ConfigMap)

```powershell
kubectl apply -f kubernetes\databases\
kubectl -n mlops wait pod/postgres-0 --for=condition=ready --timeout=180s
```

### 3.3 Bootstrap manual de schemas

El `postgres-init` ConfigMap crea las DBs `airflow`, `mlflow`, `mlops`, pero
el `\connect mlops` falla en script de init. Por eso aplicamos el SQL completo a mano:

```powershell
Get-Content scripts\init_db.sql | kubectl -n mlops exec -i postgres-0 -- psql -U mlops -d postgres
```

Después crea el rol `mlops_user` (los Secrets lo esperan):

```powershell
kubectl -n mlops exec postgres-0 -- psql -U mlops -d postgres -c "CREATE USER mlops_user WITH PASSWORD 'mlops_pass' SUPERUSER;"
```

Verifica:

```powershell
kubectl -n mlops exec postgres-0 -- psql -U mlops -d mlops -c "\dn"
# Esperado: clean_data, public, raw_data

kubectl -n mlops exec postgres-0 -- psql -U mlops -d mlops -c "\dt raw_data.*"
# Esperado: 5 tablas (raw_batches, row_hashes, category_catalog, inference_events, training_audit)
```

### 3.4 MinIO + crear bucket

```powershell
kubectl apply -f kubernetes\minio\
kubectl -n mlops wait pod -l app=minio --for=condition=ready --timeout=120s

kubectl -n mlops run mc-bucket --rm -i --image=minio/mc:latest --restart=Never --command -- sh -c "mc alias set local http://minio:9000 minio_admin minio_secret123 ; mc mb -p local/mlflow-artifacts ; mc ls local/"
```

### 3.5 Resto de componentes

```powershell
kubectl apply -f kubernetes\mlflow\
kubectl apply -f kubernetes\data-api\
kubectl apply -f kubernetes\fastapi\
kubectl apply -f kubernetes\streamlit\
kubectl apply -f kubernetes\prometheus\
kubectl apply -f kubernetes\grafana\
kubectl apply -f kubernetes\airflow\
```

### 3.6 Services alias `*-service` (los Secrets los esperan)

Los Services se crean como `postgres`, `mlflow`, `minio`, etc., pero los Secrets
apuntan a `postgres-service`, `mlflow-service`, etc. Aplicar este patch:

```powershell
@'
apiVersion: v1
kind: Service
metadata: { name: postgres-service, namespace: mlops }
spec: { selector: { app: postgres }, ports: [{ port: 5432, targetPort: 5432 }] }
---
apiVersion: v1
kind: Service
metadata: { name: mlflow-service, namespace: mlops }
spec: { selector: { app: mlflow }, ports: [{ port: 5000, targetPort: 5000 }] }
---
apiVersion: v1
kind: Service
metadata: { name: minio-service, namespace: mlops }
spec:
  selector: { app: minio }
  ports:
    - { name: api, port: 9000, targetPort: 9000 }
    - { name: console, port: 9001, targetPort: 9001 }
---
apiVersion: v1
kind: Service
metadata: { name: fastapi-service, namespace: mlops }
spec: { selector: { app: fastapi }, ports: [{ port: 8000, targetPort: 8000 }] }
---
apiVersion: v1
kind: Service
metadata: { name: streamlit-service, namespace: mlops }
spec: { selector: { app: streamlit }, ports: [{ port: 8501, targetPort: 8501 }] }
---
apiVersion: v1
kind: Service
metadata: { name: grafana-service, namespace: mlops }
spec: { selector: { app: grafana }, ports: [{ port: 3000, targetPort: 3000 }] }
---
apiVersion: v1
kind: Service
metadata: { name: streamlit-nodeport, namespace: mlops }
spec:
  type: NodePort
  selector: { app: streamlit }
  ports: [{ port: 8501, targetPort: 8501, nodePort: 30501 }]
'@ | kubectl apply -f -
```

### 3.7 ConfigMap de Locust

```powershell
kubectl -n mlops create configmap locustfile-config --from-file=locustfile.py=locust\locustfile.py
```

---

## 4. Esperar a que todos los pods estén Running

```powershell
kubectl -n mlops get pods -w
# Ctrl+C cuando veas los 11 pods Running 1/1 o 2/2
```

Si después de 5 min hay pods en `Error`, `OOMKilled` o `CrashLoopBackOff`:

```powershell
# Borrarlos uno por uno; el deployment los recrea
kubectl -n mlops get pods | Select-String "Error|OOMKilled|CrashLoopBackOff"
kubectl -n mlops delete pod <nombre-del-pod>
```

---

## 5. Crear el usuario admin de Airflow

```powershell
kubectl -n mlops exec deploy/airflow -c airflow-webserver -- airflow users create --username admin --password admin --firstname Admin --lastname User --role Admin --email admin@mlops.local
```

---

## 6. Instalar Argo CD

```powershell
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/v2.11.4/manifests/install.yaml
kubectl -n argocd rollout status deployment argocd-server --timeout=240s

# Aplicar la Application
kubectl apply -f kubernetes\argocd\application.yaml

# Activar recursión (sin esto solo sincroniza top-level)
kubectl -n argocd patch application mlops-proyecto-final --type merge -p '{\"spec\":{\"source\":{\"directory\":{\"recurse\":true}}}}'

# Obtener password
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | ForEach-Object { [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($_)) }
```

Guarda ese password. El user es `admin`.

---

## 7. Disparar primer entrenamiento del DAG

⚠️ **El training consume mucha RAM** (~2 GB pico). Antes de disparar:

- Cierra Chrome, Discord, Spotify, IDE extra
- Asegúrate que Docker Desktop tenga 8+ GB asignados (paso 0.1)
- No abras varias pestañas del navegador todavía

```powershell
# Resetear el state de la data-api a batch 0
kubectl -n mlops exec deploy/airflow -c airflow-scheduler -- python -c "import urllib.request; print(urllib.request.urlopen('http://data-api:80/restart_data_generation?group_number=1').read().decode())"

# Despausar y disparar el DAG
kubectl -n mlops exec deploy/airflow -c airflow-scheduler -- airflow dags unpause real_estate_mlops_pipeline
kubectl -n mlops exec deploy/airflow -c airflow-scheduler -- airflow dags trigger real_estate_mlops_pipeline -r "first-run"
```

Tarda ~12-15 min. Monitorea con:

```powershell
kubectl -n mlops exec deploy/airflow -c airflow-scheduler -- airflow dags list-runs -d real_estate_mlops_pipeline
```

Si Docker Desktop se cuelga durante el training (síntoma: `kubectl` da TLS handshake timeout):
1. Restart Docker Desktop (click derecho icono → Restart)
2. Esperar a ballena verde (~2-3 min)
3. Los pods reaparecen solos

---

## 8. Validar el sistema

```powershell
# 1. Pods
kubectl -n mlops get pods

# 2. FastAPI con modelo cargado
curl.exe -s http://localhost:30800/health
# Esperado: {"status":"ok","model_loaded":true,"model_version":"1","model_alias":"production"}

# 3. Datos en tablas
kubectl -n mlops exec postgres-0 -- psql -U mlops -d mlops -c "SELECT 'raw_batches' AS t, COUNT(*) FROM raw_data.raw_batches UNION ALL SELECT 'training_audit', COUNT(*) FROM raw_data.training_audit UNION ALL SELECT 'inference_events', COUNT(*) FROM raw_data.inference_events;"

# 4. Predict en vivo
$body = @{
    brokered_by = "agency_42"; status = "for_sale"; bed = 3; bath = 2
    acre_lot = 0.25; street = "street_100"; city = "New York"
    state = "NY"; zip_code = 10001; house_size = 1800; prev_sold_date = $null
} | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:30800/predict" -Method Post -Body $body -ContentType "application/json"
# Esperado: price ~$234000, model_version: "1", model_alias: "production"
```

---

## 9. Lanzar Locust (opcional, para generar histórico en Grafana)

```powershell
kubectl -n mlops exec deploy/locust -- locust --headless -u 50 -r 5 -t 60s --host http://fastapi:8000 -f /locust/locustfile.py --only-summary
```

Genera ~300-500 inferencias en 60s.

---

## 10. Acceder a las UIs

| Servicio | URL | Credenciales |
|---|---|---|
| **Airflow** | http://localhost:30808 | admin / admin |
| **MLflow** | http://localhost:30500 | — |
| **FastAPI Swagger** | http://localhost:30800/docs | — |
| **Streamlit** | http://localhost:30501 | — |
| **Grafana** | http://localhost:30300 | admin / admin123 |
| **Locust** | http://localhost:30089 | — |
| **MinIO Console** | http://localhost:30901 | minio_admin / minio_secret123 |
| **Prometheus** | http://localhost:30909 | — |
| **Argo CD** | https://localhost:8443 (port-forward) | admin / (paso 6) |

Para Argo CD, abrir en otra terminal y dejar corriendo:

```powershell
kubectl -n argocd port-forward svc/argocd-server 8443:443
```

---

## 11. Si algo se rompe

| Síntoma | Solución |
|---|---|
| Pod en `ImagePullBackOff` | Verificar paso 2 (build local) — la imagen no está en DockerHub |
| Pod en `OOMKilled` | `kubectl delete pod <nombre>`; subir RAM en `.wslconfig` |
| `kubectl` con TLS timeout | Restart Docker Desktop |
| `Error: role "mlops_user" does not exist` | Repetir paso 3.3 |
| MLflow tirando 500 | Verificar bucket `mlflow-artifacts` creado en paso 3.4 |
| FastAPI 503 sin modelo | Disparar el DAG (paso 7) y esperar a que termine |
| Streamlit "Connection refused" | `kubectl delete pod -l app=streamlit` |

---

## 12. Reset total (si todo se va al pasto)

```powershell
# Borra TODO del namespace mlops y reinicia desde paso 3
kubectl delete namespace mlops --wait=false
# Esperar ~30s
kubectl get namespace mlops
# Si sigue Terminating, forzar:
kubectl get namespace mlops -o json | ConvertFrom-Json | ForEach-Object {
    $_.spec.finalizers = @()
    $_ | ConvertTo-Json -Depth 10
} | kubectl replace --raw "/api/v1/namespaces/mlops/finalize" -f -

# Luego volver al paso 3
```

---

## 📞 Cualquier cosa que falle, avisarle al equipo

El sistema ya fue validado end-to-end en otra máquina. Si algo falla acá,
seguramente es por algún detalle del entorno (RAM, versiones de Docker Desktop,
firewall corporativo). El guion del video está en `docs/video_sustentacion.md`.

— Equipo MLOps 2026-1
