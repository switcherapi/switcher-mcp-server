FROM python:3.15-alpine

ENV APP_HOME=/home/app
RUN addgroup -S app \
    && adduser -S app -G app

WORKDIR $APP_HOME

COPY Pipfile Pipfile.lock ./

RUN pip install --upgrade pip && \
    pip install pipenv && \
    pipenv install --deploy --system --ignore-pipfile && \
    pip uninstall -y pipenv

COPY switcher_mcp_server ./switcher_mcp_server

RUN chown -R app:app "$APP_HOME"
USER app

CMD ["python", "-m", "switcher_mcp_server.server"]
