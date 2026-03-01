FROM python:3.12-slim

WORKDIR /workspace

COPY . /workspace

RUN pip install --no-cache-dir -e .

CMD ["sh", "-lc", "seedpipe-compile && seedpipe-watch --pipeline all --poll-seconds 5 --inbox-root /inbox --inputs-root /artifacts/inputs --outputs-root /artifacts/outputs --outbox-root /workspace/outbox"]
