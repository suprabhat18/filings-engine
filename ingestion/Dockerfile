FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /job

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY edgar ./edgar
COPY sp100.txt .

CMD ["python", "-m", "edgar.update"]
