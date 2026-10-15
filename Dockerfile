FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md uv.lock ./
COPY src ./src
COPY prompts ./prompts
RUN pip install --no-cache-dir .
COPY app.py ./
COPY ui ./ui
COPY .streamlit ./.streamlit
COPY tests/fixtures ./tests/fixtures
RUN useradd --create-home dataforge && mkdir /data && chown dataforge:dataforge /data
USER dataforge
ENV DATAFORGE_HOME=/data
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health')"
CMD ["python", "-m", "streamlit", "run", "app.py", "--server.address", "0.0.0.0"]
