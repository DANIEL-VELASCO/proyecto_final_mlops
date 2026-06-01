FROM apache/airflow:2.9.2

USER root

# CLI de Docker + libs de compilacion para drivers Python.
# El DAG invoca `docker run` para correr la imagen de training, asi que el CLI
# es indispensable. El acceso al daemon se da montando /var/run/docker.sock en
# el manifest de Kubernetes (DinD/dind-style, OK para Docker Desktop K8s).
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ libpq-dev curl ca-certificates gnupg lsb-release \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# Permitir que el usuario airflow corra docker (gid 999 = docker en muchas distros;
# si no funciona, en el manifest agregamos un initContainer que chown -R el socket).
RUN groupadd -f docker && usermod -aG docker airflow

USER airflow
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY dags/ /opt/airflow/dags/
