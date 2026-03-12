import socket
import threading
import struct

# Função para receber mensagens do servidor

def receber_mensagens(cliente_socket):
    while True:
        try:
            # Receber pacote RTP
            pacote, _ = cliente_socket.recvfrom(2048)
            # Extrair header RTP
            header = pacote[:12]  # Os primeiros 12 bytes são o header RTP
            # Processar o header (exemplo: imprimir)
            print(f"Header RTP recebido: {header.hex()}")
            # Decodificar a mensagem
            mensagem = pacote[12:]
            print(f"Mensagem recebida: {mensagem.decode('utf-8')}")
        except:
            break

# Função do cliente UDP

def cliente_rtp():
    host = '127.0.0.1'  # Endereço IP do servidor
    porta = 12345       # Porta do servidor

    cliente_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    nome = input("Digite seu nome: ")
    print(f"Conectado ao servidor RTP em {host}:{porta}")

    # Thread para receber mensagens do servidor
    threading.Thread(target=receber_mensagens, args=(cliente_socket,), daemon=True).start()

    while True:
        mensagem = input(f"{nome}: ")
        if mensagem.lower() == 'sair':
            print("Encerrando conexão.")
            break
        mensagem_completa = f"{nome}: {mensagem}"
        # Enviar pacote RTP (com header)
        header_rtp = struct.pack('!BBHII', 0x80, 96, 0, 0, 0)  # Exemplo de header RTP
        pacote_rtp = header_rtp + mensagem_completa.encode('utf-8')
        cliente_socket.sendto(pacote_rtp, (host, porta))

    cliente_socket.close()

if __name__ == "__main__":
    cliente_rtp()