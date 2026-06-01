import random
from locust import HttpUser, task, between

CITIES = ["New York", "Los Angeles", "Chicago", "Houston", "Phoenix",
          "Philadelphia", "San Antonio", "San Diego", "Dallas", "San Jose"]
STATES = ["NY", "CA", "IL", "TX", "AZ", "PA", "FL", "OH", "GA", "NC"]
STATUSES = ["for_sale", "for_build"]


class InferenceUser(HttpUser):
    """Simula un usuario que realiza peticiones de inferencia a la API."""

    wait_time = between(1, 3)

    @task(8)
    def predict(self):
        payload = {
            "brokered_by": f"agency_{random.randint(1, 200)}",
            "status": random.choice(STATUSES),
            "bed": random.randint(1, 7),
            "bath": random.randint(1, 5),
            "acre_lot": round(random.uniform(0.05, 5.0), 2),
            "street": f"street_{random.randint(1, 5000)}",
            "city": random.choice(CITIES),
            "state": random.choice(STATES),
            "zip_code": random.randint(10000, 99999),
            "house_size": random.randint(400, 8000),
            "prev_sold_date": None,
        }
        with self.client.post(
            "/predict",
            json=payload,
            catch_response=True,
            name="/predict",
        ) as response:
            if response.status_code == 200:
                data = response.json()
                if "price" not in data:
                    response.failure("Respuesta sin campo 'price'")
            elif response.status_code == 503:
                response.failure("Modelo no disponible (503)")
            else:
                response.failure(f"Status inesperado: {response.status_code}")

    @task(2)
    def health_check(self):
        with self.client.get("/health", catch_response=True, name="/health") as response:
            if response.status_code != 200:
                response.failure(f"Health check falló: {response.status_code}")
