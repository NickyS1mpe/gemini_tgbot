FROM python:3.11-slim

WORKDIR /usr/src/app

COPY . .

RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONPATH=/usr/src/app

CMD ["python", "app/bot.py"]