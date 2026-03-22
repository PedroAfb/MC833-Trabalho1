import os
import socket
import struct
import threading
import time
from pathlib import Path

SERVER_IP = os.getenv("SERVER_IP", "10.0.1.2")
CONTROL_PORT = int(os.getenv("CONTROL_PORT", "9000"))
DEFAULT_DATA_PORT = int(os.getenv("CLIENT_DATA_PORT", "5006"))
STREAM_OUTPUT_DIR = Path(__file__).resolve().parent / "streams"


def parse_rtp_header(packet: bytes):
    if len(packet) < 12:
        raise ValueError("Pacote menor que 12 bytes (header RTP incompleto)")

    b0, b1, seq, timestamp, ssrc = struct.unpack("!BBHII", packet[:12])
    version = (b0 >> 6) & 0b11
    marker = (b1 >> 7) & 0b1
    payload_type = b1 & 0x7F
    payload = packet[12:]

    return {
        "version": version,
        "marker": marker,
        "payload_type": payload_type,
        "seq": seq,
        "timestamp": timestamp,
        "ssrc": ssrc,
        "payload": payload,
    }


def parse_ethernet_ipv4_udp(frame: bytes):
    if len(frame) < 14 + 20 + 8:
        return None

    ethertype = struct.unpack("!H", frame[12:14])[0]
    if ethertype != 0x0800:  # IPv4
        return None

    ip_offset = 14
    ihl = (frame[ip_offset] & 0x0F) * 4
    if ihl < 20:
        return None

    protocol = frame[ip_offset + 9]
    if protocol != 17:  # UDP
        return None

    udp_offset = ip_offset + ihl
    if len(frame) < udp_offset + 8:
        return None

    src_port, dst_port, udp_length, _ = struct.unpack("!HHHH", frame[udp_offset : udp_offset + 8])
    payload_offset = udp_offset + 8
    payload_end = udp_offset + udp_length
    if payload_end > len(frame):
        payload_end = len(frame)

    payload = frame[payload_offset:payload_end]
    return src_port, dst_port, payload


class ReceptorRTP:
    def __init__(self, data_socket: socket.socket, output_file: Path) -> None:
        self.data_socket = data_socket
        self.output_file = output_file
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.expected_seq: int | None = None
        self.recebidos = 0
        self.perdidos = 0

    def start(self) -> None:
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)

    def _run(self) -> None:
        STREAM_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.data_socket.settimeout(0.8)
        timeouts_consecutivos = 0

        with self.output_file.open("wb") as f:
            while not self.stop_event.is_set():
                try:
                    packet, _ = self.data_socket.recvfrom(65535)
                except socket.timeout:
                    timeouts_consecutivos += 1
                    if timeouts_consecutivos >= 6:
                        # Considera stream finalizado por inatividade (sem pacote por ~4.8s)
                        break
                    continue
                except OSError:
                    break

                timeouts_consecutivos = 0

                try:
                    h = parse_rtp_header(packet)
                except ValueError:
                    continue

                seq = h["seq"]
                if self.expected_seq is not None and seq != self.expected_seq:
                    delta = (seq - self.expected_seq) & 0xFFFF
                    if delta > 0:
                        self.perdidos += delta

                self.expected_seq = (seq + 1) & 0xFFFF

                f.write(h["payload"])
                self.recebidos += 1

                if self.recebidos <= 5 or self.recebidos % 200 == 0:
                    print(
                        f"[RTP] seq={h['seq']} ts={h['timestamp']} pt={h['payload_type']} "
                        f"payload={len(h['payload'])}B"
                    )


def receber_controle_esperado(control_socket: socket.socket, aceitos: tuple[str, ...], timeout_total: float = 4.0):
    inicio = time.time()
    while time.time() - inicio < timeout_total:
        restante = max(0.2, timeout_total - (time.time() - inicio))
        control_socket.settimeout(restante)
        dados, _ = control_socket.recvfrom(4096)
        texto = dados.decode("utf-8", errors="ignore").strip()
        if texto.startswith(aceitos):
            return texto

        # Mensagens assíncronas esperadas
        print(f"[CTRL] {texto}")

    raise socket.timeout("timeout aguardando resposta de controle")


def iniciar_sniffer_raw(data_port: int) -> None:
    """
    Listener raw (AF_PACKET) para inspecionar pacotes em L2 e extrair header RTP do payload UDP.
    """

    def _sniff() -> None:
        try:
            listener = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.ntohs(3))
        except Exception as e:
            print(f"[RAW] Listener indisponível: {e}")
            return

        print("[RAW] Listener AF_PACKET ativo para inspeção dos headers RTP")
        vistos = 0
        while True:
            try:
                frame, _ = listener.recvfrom(65535)
            except Exception:
                break

            parsed = parse_ethernet_ipv4_udp(frame)
            if not parsed:
                continue

            src_port, dst_port, payload = parsed
            if dst_port != data_port and src_port != data_port:
                continue
            if len(payload) < 12:
                continue

            try:
                h = parse_rtp_header(payload)
            except ValueError:
                continue

            vistos += 1
            if vistos <= 3 or vistos % 300 == 0:
                print(
                    f"[RAW/RTP] seq={h['seq']} ts={h['timestamp']} "
                    f"pt={h['payload_type']} payload={len(h['payload'])}B"
                )

    t = threading.Thread(target=_sniff, daemon=True)
    t.start()


def solicitar_catalogo(control_socket: socket.socket):
    control_socket.sendto(b"CATALOG", (SERVER_IP, CONTROL_PORT))
    texto = receber_controle_esperado(control_socket, ("CATALOG ", "CATALOG_EMPTY"), timeout_total=4.0)

    if texto == "CATALOG_EMPTY":
        print("Catalogo vazio no servidor.")
        return []

    if not texto.startswith("CATALOG "):
        print(f"Resposta inesperada: {texto}")
        return []

    itens = texto[len("CATALOG ") :].split("|")
    videos = []
    print("\n=== CATALOGO ===")
    for item in itens:
        try:
            vid, nome = item.split(":", 1)
            videos.append((int(vid), nome))
            print(f"{vid} - {nome}")
        except ValueError:
            continue
    print("===============\n")
    return videos


def cliente_rtp() -> None:
    print(f"Conectando ao servidor de controle em {SERVER_IP}:{CONTROL_PORT}")

    control_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    control_socket.settimeout(4.0)

    data_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    data_socket.bind(("0.0.0.0", DEFAULT_DATA_PORT))

    # Habilita listener raw para inspeção dos pacotes (conforme requisito do lab)
    iniciar_sniffer_raw(DEFAULT_DATA_PORT)

    receptor: ReceptorRTP | None = None

    try:
        while True:
            print("1) Catalogo")
            print("2) Stream")
            print("3) Stop")
            print("4) Sair")
            opcao = input("Escolha: ").strip()

            if opcao == "1":
                try:
                    solicitar_catalogo(control_socket)
                except socket.timeout:
                    print("Timeout ao pedir catalogo")

            elif opcao == "2":
                try:
                    videos = solicitar_catalogo(control_socket)
                except socket.timeout:
                    print("Timeout ao pedir catalogo")
                    continue

                if not videos:
                    continue

                escolha = input("Digite o id do video: ").strip()
                try:
                    video_id = int(escolha)
                except ValueError:
                    print("Id inválido")
                    continue

                nome_arquivo = next((nome for vid, nome in videos if vid == video_id), f"video_{video_id}.ts")
                output = STREAM_OUTPUT_DIR / f"recebido_{int(time.time())}_{nome_arquivo}"

                if receptor:
                    receptor.stop()

                receptor = ReceptorRTP(data_socket, output)
                receptor.start()

                cmd = f"STREAM {video_id} {DEFAULT_DATA_PORT}".encode("utf-8")
                control_socket.sendto(cmd, (SERVER_IP, CONTROL_PORT))

                try:
                    ack_txt = receber_controle_esperado(control_socket, ("OK", "ERROR"), timeout_total=4.0)
                    print(f"Servidor: {ack_txt}")
                except socket.timeout:
                    print("Sem resposta imediata do servidor ao iniciar stream")

                print(f"Gravando stream em: {output}")
                print("Você pode abrir em paralelo com: mpv <arquivo.ts> ou vlc <arquivo.ts>")

            elif opcao == "3":
                control_socket.sendto(b"STOP", (SERVER_IP, CONTROL_PORT))
                try:
                    ack_txt = receber_controle_esperado(control_socket, ("OK", "ERROR"), timeout_total=4.0)
                    print(f"Servidor: {ack_txt}")
                except socket.timeout:
                    print("Sem ACK para STOP")

                if receptor:
                    receptor.stop()
                    print(
                        f"Recepção finalizada. pacotes={receptor.recebidos}, "
                        f"perdas_detectadas={receptor.perdidos}"
                    )

            elif opcao == "4":
                if receptor:
                    receptor.stop()
                    print(
                        f"Recepção finalizada. pacotes={receptor.recebidos}, "
                        f"perdas_detectadas={receptor.perdidos}"
                    )
                break

            else:
                print("Opção inválida")

    finally:
        data_socket.close()
        control_socket.close()


if __name__ == "__main__":
    cliente_rtp()