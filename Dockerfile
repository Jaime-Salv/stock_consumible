FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    build-essential \
    libxrender1 \
    libxext6 \
    libfontconfig1 \
    wkhtmltopdf \
    && apt-get clean

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 8000
CMD ["uvicorn", "app.app:app", "--host", "0.0.0.0", "--port", "8000"]


