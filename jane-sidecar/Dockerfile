FROM python:3.12-slim

WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN useradd --create-home --uid 10001 jane
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY CONSTITUTION.md ./CONSTITUTION.md
COPY jane ./jane
COPY docker-entrypoint.sh /srv/docker-entrypoint.sh
RUN chmod 755 /srv/docker-entrypoint.sh
USER jane

EXPOSE 8000
ENTRYPOINT ["/srv/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
