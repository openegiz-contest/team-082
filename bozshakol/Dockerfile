FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY sim ./sim
COPY twins ./twins
# Open datasets (with their licences) and the trained models, evaluated in pure Python.
COPY data ./data
COPY ml/models ./ml/models
# files may arrive without read permission for others (archives, uploads): the model runs as nobody
RUN chmod -R a+rX /app
USER nobody
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "sim.main"]
