## Ambiente dos Estudantes

É através desse ambiente ao qual você irá realizar uma bagatela de experimentos e testes durante a disciplina.

Ele é feito em docker com inicialmente com cliente, roteador e servidor.

Os arquivos client.py, server.py e roteador.py nas respectivas pastas são mapeados direto para os containers gerados pelo docker compose e docker file. Dessa forma, mantenha eles sempre com o mesmo nome e arvore de diretórios. Você pode criar novos arquivos e alterar como bem entender o corpo de cada um deses scripts desde que mantenha os nomes iguais.

O primeiro passo é instalar o [docker](https://docs.docker.com/desktop/setup/install/windows-install/). Siga os tutorias disponibilizados no site.

Crie as imagens utilizando o seguinte comando:

```bash
~$ docker compose up -d 
```

Para remover os containers use
```bash
~$ docker compose down
```

Se você desejar executar algum comando em algum container você fazer algo semelhante:

```bash
docker exec -it nome_do_container tcpdump -i any udp
```

nesse comando executamos o comando tcpdump para capturar os pacotes que passam pela máquina que são UDP. Isso é util durante o processo de criação do código de vocês.