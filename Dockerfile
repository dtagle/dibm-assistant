# Imagen del DIBM Assistant (spec 04, punto 5).
FROM python:3.12-slim

# Sin archivos .pyc y con la salida sin búfer, para que el log JSON salga al momento
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Primero las dependencias, para aprovechar la caché de capas de Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Solo lo que el servicio necesita: el código y los datos
COPY app/ app/
COPY data/ data/

# Usuario sin privilegios: el proceso nunca corre como root
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Render pone el puerto en PORT; en local se usa 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
