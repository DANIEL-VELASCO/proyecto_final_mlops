FROM locustio/locust:2.28.0

WORKDIR /locust

COPY locustfile.py .

EXPOSE 8089

ENTRYPOINT ["locust", "-f", "locustfile.py"]
