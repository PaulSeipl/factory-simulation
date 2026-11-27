# The MES planner: mes_bridge with the thesis scheduler, for the MES's docker compose (service `planner`).
# Build from the repository root (mes_bridge depends on the thesis package through `path = ".."`):
#   docker build -f mes_bridge/Dockerfile -t ghcr.io/fidentis-gmbh/mes-planner:v0.1.0 .
# Publishing: mes_bridge/PUBLISH.md.

FROM python:3.14-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.6 /uv /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /src
COPY pyproject.toml README.md ./
COPY src ./src
COPY mes_bridge/pyproject.toml mes_bridge/uv.lock ./mes_bridge/
COPY mes_bridge/src ./mes_bridge/src
# non-editable: both packages land in the virtual environment, the sources are not needed at run time
RUN cd mes_bridge && UV_PROJECT_ENVIRONMENT=/app/.venv uv sync --frozen --no-dev --no-editable

FROM python:3.14-slim
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
RUN useradd --system --uid 10001 planner && mkdir /data && chown planner /data
USER planner
WORKDIR /data
VOLUME /data
EXPOSE 8765
# MES_URL, MES_SCHEDULER_PASSWORD and MES_EVENTS_TOKEN come from the environment (never baked in)
ENTRYPOINT ["python", "-m", "mes_bridge.runner", "--host", "0.0.0.0", "--port", "8765", "--state-dir", "/data"]
