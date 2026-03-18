# Relatorio Tecnico - Streaming de Video com RTP em Raw Sockets

Disciplina: MC833
Aluno: Pedro Borges
RA: 260628
Repositorio: MC833-Trabalho1

## 1. Protocolo utilizado e diagrama de sequencia

Implementacao adotada:
- Transporte: IPv4 + UDP montado manualmente em raw socket.
- Midia: RTP minimo (header fixo de 12 bytes).
- Controle de aplicacao: comandos textuais no payload UDP.

Fluxo de controle e dados:

Justificativa dos campos RTP escolhidos:
1. Version (2): conformidade com RTP padrao.
2. Payload Type (33): valor comum para MPEG-TS sobre RTP.
3. Sequence Number: permite detectar perda e reordenacao.
4. Timestamp: permite sincronizacao temporal da reproducao.
5. SSRC: identifica univocamente a fonte do stream.

## 2. Estrutura dos cabecalhos e bytes reservados

Estrutura por pacote de dados:
1. Header IPv4: 20 bytes
2. Header UDP: 8 bytes
3. Header RTP: 12 bytes
4. Payload de dados TS: ate 1300 bytes

Total de overhead fixo por pacote:
- 40 bytes

Quantidade de bytes reservados exclusivamente para dados:
- ate 1300 bytes por pacote (payload RTP)

## 3. Pacotes por frame para cada video (30 fps)

Fonte dos dados:
- Arquivo metrics_report.json gerado pelo servidor.

Tabela (valores coletados no teste):

| Video | Tamanho (bytes) | Pacotes totais | Frames estimados (30fps) | Pacotes por frame |
|---|---:|---:|---:|---:|
| mengao.ts | 4807160 | 3698 | 878.498 | 4.209457 |
| nesk.ts | 16419544 | 12631 | 1542.27 | 8.189878 |
| too_easy.ts | 6483932 | 4988 | 200.527 | 24.874416 |

Formula usada:
- pacotes_por_frame = pacotes_totais / (duracao_segundos * 30)

## 4. Taxa de transmissao para manter stream a 30 fps

Tabela (valores coletados no teste):

| Video | Taxa estimada (Mbps) a 30fps |
|---|---:|
| mengao.ts | 1.353762 |
| nesk.ts | 2.633865 |
| too_easy.ts | 7.999612 |

Formula usada:
1. pacotes_por_segundo = pacotes_por_frame * 30
2. taxa_bps = pacotes_por_segundo * (payload_por_pacote + overhead_por_pacote) * 8
3. taxa_mbps = taxa_bps / 1_000_000

Com os parametros implementados:
- payload_por_pacote = 1300 bytes
- overhead_por_pacote = 40 bytes

Leitura breve dos resultados:
1. `too_easy.ts` teve a maior carga por frame (24.874416 pacotes/frame) e maior taxa estimada (7.999612 Mbps).
2. `mengao.ts` apresentou a menor taxa estimada (1.353762 Mbps), com menor densidade de pacotes por frame.
3. A taxa de transmissao nao depende apenas do tamanho total do arquivo, mas tambem da duracao do video (mais curto tende a exigir taxa maior para manter 30 fps).

## 5. Uso de IA
Ferramenta utilizada:
- GitHub Copilot

Partes em que a IA foi utilizada:
1. Escrita inicial das funcoes de pacote IP/UDP e RTP.
2. Sugestao de validacoes de robustez na recepcao (ordem, duplicata, perda estimada).
3. Organizacao do roteiro de testes e do modelo de relatorio.
