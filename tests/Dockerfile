FROM python:3.12-slim

ENV \
    # Allow statements and log messages to immediately appear in the logs
    PYTHONUNBUFFERED=1 \
    # source is bind-mounted read-only, so don't try to write .pyc next to it
    PYTHONDONTWRITEBYTECODE=1 \
    # disable a pip version check to reduce run-time & log-spam
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # cache is useless in docker image, so disable to reduce image size
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first: editing source then leaves these layers cached.
COPY requirements.txt ./requirements.txt
COPY tests/requirements.txt ./tests/requirements.txt
RUN pip install -r requirements.txt -r tests/requirements.txt

# compose bind-mounts release/ and tests/ over the top for the dev loop; copying
# them in keeps the image runnable on its own (CI, or a bare `docker run`).
COPY pytest.ini ./pytest.ini
COPY release/ ./release/
COPY tests/ ./tests/

CMD ["pytest"]
