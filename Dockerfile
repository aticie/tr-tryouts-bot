FROM python:3.10-slim

WORKDIR /app/

COPY requirements.txt /app/requirements.txt

RUN pip install -r requirements.txt

COPY . /app/

ENTRYPOINT ["python3", "main.py"]