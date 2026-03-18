# Laboratorio MC833 - Streaming RTP em Raw Sockets

## Setup rapido

1. Suba os containers:

```bash
docker compose up -d
```

2. Sincronize os arquivos do projeto para dentro dos containers:

```bash
./copy-files.sh
```

3. Verifique se os containers estao no ar:

```bash
docker compose ps
```

## Rodando a aplicacao

1. Em um terminal, inicie o servidor:

```bash
docker exec -it servidor python3 /app/server.py
```

2. Em outro terminal, inicie o cliente:

```bash
docker exec -it client python3 /app/client.py
```

## Workflow de uso (streaming)

No prompt do cliente, use:

```text
catalog
metrics
stream <nome_video.ts>
q
```

Fluxo recomendado:

1. Rode `catalog` para listar os videos disponiveis no servidor.
2. Rode `stream <nome_video.ts>` para receber um video.
3. O arquivo recebido sera salvo em `./cliente/downloads/received_<nome_video.ts>`.
4. Rode `metrics` quando quiser gerar o relatorio de metricas no servidor.

## Workflow de desenvolvimento

Sempre que alterar `cliente/client.py`, `servidor/server.py` ou outros arquivos dessas pastas:

1. Rode novamente:

```bash
./copy-files.sh
```

2. Reinicie servidor e cliente.

## Copiando resultados para o host

Copiar video recebido do cliente:

```bash
docker cp client:/app/downloads/received_mengao.ts ./received_mengao.ts
```

Copiar metricas do servidor:

```bash
docker cp servidor:/app/metrics_report.json ./metrics_report.json
```
