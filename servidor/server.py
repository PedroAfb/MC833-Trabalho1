import os
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path

SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
CONTROL_PORT = int(os.getenv("CONTROL_PORT", "9000"))
RTP_SOURCE_PORT = int(os.getenv("RTP_SOURCE_PORT", "5004"))
VIDEO_DIR = Path(__file__).resolve().parent / "videos"

# RTP (MPEG-TS over RTP)
RTP_VERSION = 2
RTP_PAYLOAD_TYPE = 33
RTP_CLOCK = 90_000
TARGET_FPS = 30
RTP_TIMESTAMP_STEP = RTP_CLOCK // TARGET_FPS  # 3000

# 7 pacotes TS (188 bytes) por payload RTP -> 1316 bytes
TS_PACKET_SIZE = 188
TS_PER_RTP = 7
RTP_PAYLOAD_SIZE = TS_PACKET_SIZE * TS_PER_RTP


def listar_videos_ts() -> list[Path]:
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    return sorted([p for p in VIDEO_DIR.glob("*.ts") if p.is_file()])


def montar_pacote_rtp(payload: bytes, seq: int, timestamp: int, ssrc: int, marker: int = 0) -> bytes:
    b0 = (RTP_VERSION & 0b11) << 6  # V=2, P=0, X=0, CC=0
    b1 = ((marker & 0x1) << 7) | (RTP_PAYLOAD_TYPE & 0x7F)
    header = struct.pack("!BBHII", b0, b1, seq & 0xFFFF, timestamp & 0xFFFFFFFF, ssrc & 0xFFFFFFFF)
    return header + payload


def estimar_intervalo_envio(video_path: Path) -> float:
    """
    Estima pacing com base na duração real do vídeo para manter streaming suave.
    Fallback para 1ms entre pacotes caso não consiga medir duração.
    """
    tamanho = video_path.stat().st_size
    duracao = None

    try:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
        saida = subprocess.check_output(cmd, text=True).strip()
        duracao = float(saida)
    except Exception:
        duracao = None

    if not duracao or duracao <= 0:
        return 0.001

    total_pacotes = max(1, (tamanho + RTP_PAYLOAD_SIZE - 1) // RTP_PAYLOAD_SIZE)
    pacotes_por_segundo = max(1.0, total_pacotes / duracao)
    return 1.0 / pacotes_por_segundo


class SessaoStream:
    def __init__(self) -> None:
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self.ativa = False

    def parar(self) -> None:
        with self.lock:
            if self.thread and self.thread.is_alive():
                self.stop_event.set()
                self.thread.join(timeout=2.0)
            self.thread = None
            self.stop_event = threading.Event()
            self.ativa = False

    def iniciar(self, alvo, args: tuple) -> None:
        with self.lock:
            self.parar()
            self.stop_event = threading.Event()
            self.thread = threading.Thread(target=alvo, args=args, daemon=True)
            self.ativa = True
            self.thread.start()


def stream_video(
    data_socket: socket.socket,
    control_socket: socket.socket,
    stop_event: threading.Event,
    client_ip: str,
    client_control_addr: tuple[str, int],
    client_data_port: int,
    video_path: Path,
    video_id: int,
) -> None:
    seq = 0
    timestamp = 0
    ssrc = 0x12345678

    intervalo = estimar_intervalo_envio(video_path)
    enviados = 0
    inicio = time.time()

    print(
        f"[STREAM] Iniciando envio '{video_path.name}' para {client_ip}:{client_data_port} "
        f"(payload={RTP_PAYLOAD_SIZE} bytes, intervalo~{intervalo:.6f}s)"
    )

    try:
        with video_path.open("rb") as f:
            while not stop_event.is_set():
                payload = f.read(RTP_PAYLOAD_SIZE)
                if not payload:
                    break

                marcador = 0
                pacote = montar_pacote_rtp(payload, seq, timestamp, ssrc, marker=marcador)
                data_socket.sendto(pacote, (client_ip, client_data_port))

                seq = (seq + 1) & 0xFFFF
                timestamp = (timestamp + RTP_TIMESTAMP_STEP) & 0xFFFFFFFF
                enviados += 1

                time.sleep(intervalo)

        duracao = max(0.001, time.time() - inicio)
        taxa = enviados / duracao
        print(f"[STREAM] Fim do envio '{video_path.name}'. pacotes={enviados}, taxa~{taxa:.2f} pps")
    except Exception as e:
        print(f"[ERRO] Falha no stream: {e}")
    finally:
        msg_end = f"STREAM_END {video_id}".encode("utf-8")
        control_socket.sendto(msg_end, client_control_addr)


def servidor_rtp() -> None:
    control_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    control_socket.bind((SERVER_HOST, CONTROL_PORT))

    data_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    data_socket.bind((SERVER_HOST, RTP_SOURCE_PORT))

    sessao = SessaoStream()

    print(f"Servidor de controle em {SERVER_HOST}:{CONTROL_PORT}")
    print(f"Servidor RTP (dados) em {SERVER_HOST}:{RTP_SOURCE_PORT}")
    print(f"Diretório de vídeos: {VIDEO_DIR}")

    while True:
        dados, addr = control_socket.recvfrom(2048)
        texto = dados.decode("utf-8", errors="ignore").strip()
        if not texto:
            continue

        partes = texto.split()
        comando = partes[0].upper()

        if comando == "CATALOG":
            videos = listar_videos_ts()
            if not videos:
                control_socket.sendto(b"CATALOG_EMPTY", addr)
                continue

            itens = [f"{i}:{v.name}" for i, v in enumerate(videos, start=1)]
            resposta = "CATALOG " + "|".join(itens)
            control_socket.sendto(resposta.encode("utf-8"), addr)
            continue

        if comando == "STREAM":
            # STREAM <video_id> <client_data_port>
            if len(partes) < 3:
                control_socket.sendto(b"ERROR uso: STREAM <video_id> <client_data_port>", addr)
                continue

            try:
                video_id = int(partes[1])
                client_data_port = int(partes[2])
            except ValueError:
                control_socket.sendto(b"ERROR parametros invalidos", addr)
                continue

            videos = listar_videos_ts()
            if video_id < 1 or video_id > len(videos):
                control_socket.sendto(b"ERROR video inexistente", addr)
                continue

            video_path = videos[video_id - 1]
            client_ip = addr[0]

            control_socket.sendto(f"OK STREAMING {video_id} {video_path.name}".encode("utf-8"), addr)

            sessao.iniciar(
                stream_video,
                (
                    data_socket,
                    control_socket,
                    sessao.stop_event,
                    client_ip,
                    addr,
                    client_data_port,
                    video_path,
                    video_id,
                ),
            )
            continue

        if comando == "STOP":
            sessao.parar()
            control_socket.sendto(b"OK STOPPED", addr)
            continue

        if comando == "PING":
            control_socket.sendto(b"PONG", addr)
            continue

        control_socket.sendto(b"ERROR comando desconhecido", addr)


if __name__ == "__main__":
    servidor_rtp()