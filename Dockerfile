FROM --platform=linux/arm64 ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY agent.py ./
COPY tools/ ./tools/
COPY prompts/ ./prompts/

EXPOSE 8080

CMD ["python", "agent.py"]
