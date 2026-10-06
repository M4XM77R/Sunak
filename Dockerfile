FROM python:3.12-slim
WORKDIR /app
COPY sunak ./sunak
ENV SUNAK_DATA=/data \
    SUNAK_HOST=0.0.0.0 \
    SUNAK_NO_BROWSER=1 \
    PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 7000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7000/api/status', timeout=4)"
CMD ["python", "-m", "sunak"]
