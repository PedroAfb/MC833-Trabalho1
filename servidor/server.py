import socket
import struct

# Função do servidor UDP

def servidor_rtp():
    host = '127.0.0.1'  # Endereço IP do servidor
    porta = 12345       # Porta para escutar conexões

    servidor_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    servidor_socket.bind((host, porta))

    print(f"Servidor RTP aguardando mensagens em {host}:{porta}...")

    clientes = set()  # Conjunto para armazenar endereços dos clientes

    while True:
        pacote, endereco = servidor_socket.recvfrom(2048)
        # Extrair header RTP
        header = pacote[:12]  # Os primeiros 12 bytes são o header RTP
        # Processar o header (exemplo: imprimir)
        print(f"Header RTP recebido de {endereco}: {header.hex()}")
        mensagem_decodificada = pacote[12:].decode('utf-8')

        if endereco not in clientes:
            clientes.add(endereco)

        print(f"Mensagem recebida de {endereco}: {mensagem_decodificada}")

        # Retransmitir a mensagem para todos os clientes
        for cliente in clientes:
            if cliente != endereco:  # Não enviar de volta para o remetente
                servidor_socket.sendto(pacote, cliente)

if __name__ == "__main__":
    servidor_rtp()