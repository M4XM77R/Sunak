FROM python:3.12-slim
WORKDIR /app
COPY odysseus ./odysseus
ENV ODYSSEUS_DATA=/data \
    ODYSSEUS_HOST=0.0.0.0 \
    ODYSSEUS_NO_BROWSER=1 \
    PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 7000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7000/api/status', timeout=4)"
CMD ["python", "-m", "odysseus"]
