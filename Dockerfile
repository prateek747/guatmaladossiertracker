FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY siad_lookup_service.py .

RUN mkdir -p /app/screenshots

EXPOSE 5001

CMD ["python3", "siad_lookup_service.py"]
