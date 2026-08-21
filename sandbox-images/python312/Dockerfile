FROM python:3.12-slim

# Minimal sandbox image for Python target code execution.
RUN useradd -m -s /bin/bash sandbox

WORKDIR /app
RUN chown sandbox:sandbox /app

USER sandbox

CMD ["python", "--version"]
