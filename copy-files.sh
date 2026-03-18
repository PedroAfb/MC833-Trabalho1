#!/bin/bash

set -euo pipefail

sync_service() {
	local src_dir="$1"
	local container_name="$2"

	# Remove arquivos antigos no volume montado para evitar lixo de sincronizacoes anteriores.
	docker exec "$container_name" sh -lc 'mkdir -p /app && rm -rf /app/*'
	docker cp "./${src_dir}/." "${container_name}:/app"
	# Padroniza permissao para evitar erro de leitura em ambientes com UID/GID diferentes.
	docker exec "$container_name" sh -lc 'chmod -R a+rX /app'
}

sync_service "cliente" "client"
sync_service "servidor" "servidor"
sync_service "roteador" "roteador"