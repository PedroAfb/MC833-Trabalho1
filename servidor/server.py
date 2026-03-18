import os
import socket
import struct
import subprocess
import time
import json
import math
from typing import Optional

SERVER_IP = "10.0.1.2"
SERVER_PORT = 9999
CLIENT_IP = "10.0.1.3"
CLIENT_PORT = 12345
INTERFACE = "eth0"
BUFFER_SIZE = 65535

IP_FORMAT = "!BBHHHBBH4s4s"
UDP_FORMAT = "!HHHH"
RTP_FORMAT = "!BBHII"

VIDEO_DIR = os.path.join(os.path.dirname(__file__), "videos")
VIDEO_EXT = ".ts"

RTP_VERSION = 2
RTP_PT_MPEG_TS = 33
RTP_SSRC = 0x12345678
MAX_RTP_PAYLOAD = 1300
PACKETS_PER_SECOND = 900
NETWORK_HEADER_BYTES = 20 + 8 + 12
METRICS_FILE = os.path.join(os.path.dirname(__file__), "metrics_report.json")


def checksum(msg: bytes) -> int:
    if len(msg) % 2 == 1:
        msg += b"\x00"

    total = 0
    for i in range(0, len(msg), 2):
        total += (msg[i] << 8) + msg[i + 1]

    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)

    return (~total) & 0xFFFF


def build_udp_packet(src_ip: str, dst_ip: str, src_port: int, dst_port: int, payload: bytes) -> bytes:
    udp_len = 8 + len(payload)
    ip_len = 20 + udp_len

    src_ip_b = socket.inet_aton(src_ip)
    dst_ip_b = socket.inet_aton(dst_ip)

    udp_without_checksum = struct.pack(UDP_FORMAT, src_port, dst_port, udp_len, 0)
    pseudo_header = struct.pack("!4s4sBBH", src_ip_b, dst_ip_b, 0, socket.IPPROTO_UDP, udp_len)
    udp_cksum = checksum(pseudo_header + udp_without_checksum + payload)
    udp_header = struct.pack(UDP_FORMAT, src_port, dst_port, udp_len, udp_cksum)

    ver_ihl = (4 << 4) + 5
    tos = 0
    identification = 0
    flags_frag = 0
    ttl = 64
    protocol = socket.IPPROTO_UDP
    ip_header_wo_cksum = struct.pack(
        IP_FORMAT,
        ver_ihl,
        tos,
        ip_len,
        identification,
        flags_frag,
        ttl,
        protocol,
        0,
        src_ip_b,
        dst_ip_b,
    )
    ip_cksum = checksum(ip_header_wo_cksum)
    ip_header = struct.pack(
        IP_FORMAT,
        ver_ihl,
        tos,
        ip_len,
        identification,
        flags_frag,
        ttl,
        protocol,
        ip_cksum,
        src_ip_b,
        dst_ip_b,
    )

    return ip_header + udp_header + payload


def get_ip_offset(raw_packet: bytes) -> Optional[int]:
    if len(raw_packet) < 20:
        return None

    if len(raw_packet) >= 34:
        ethertype = raw_packet[12:14]
        if ethertype == b"\x08\x00":
            return 14

    first_byte = raw_packet[0]
    version = first_byte >> 4
    if version == 4:
        return 0

    return None


def parse_udp_from_raw(raw_packet: bytes) -> Optional[dict]:
    ip_offset = get_ip_offset(raw_packet)
    if ip_offset is None or len(raw_packet) < ip_offset + 28:
        return None

    ip_base = raw_packet[ip_offset : ip_offset + 20]
    iph = struct.unpack(IP_FORMAT, ip_base)
    ihl = (iph[0] & 0x0F) * 4
    protocol = iph[6]
    src_ip = socket.inet_ntoa(iph[8])
    dst_ip = socket.inet_ntoa(iph[9])

    if protocol != socket.IPPROTO_UDP:
        return None

    udp_start = ip_offset + ihl
    if len(raw_packet) < udp_start + 8:
        return None

    src_port, dst_port, udp_len, udp_cksum = struct.unpack(UDP_FORMAT, raw_packet[udp_start : udp_start + 8])
    payload_start = udp_start + 8
    payload_end = payload_start + max(0, udp_len - 8)
    payload = raw_packet[payload_start:payload_end]

    return {
        "src_ip": src_ip,
        "dst_ip": dst_ip,
        "src_port": src_port,
        "dst_port": dst_port,
        "udp_checksum": udp_cksum,
        "payload": payload,
    }


def build_rtp_packet(sequence: int, timestamp: int, marker: int, payload: bytes) -> bytes:
    b0 = (RTP_VERSION << 6)
    b1 = ((marker & 0x01) << 7) | (RTP_PT_MPEG_TS & 0x7F)
    rtp_header = struct.pack(RTP_FORMAT, b0, b1, sequence & 0xFFFF, timestamp & 0xFFFFFFFF, RTP_SSRC)
    return rtp_header + payload


def list_videos() -> list[str]:
    if not os.path.isdir(VIDEO_DIR):
        return []

    files = []
    for entry in sorted(os.listdir(VIDEO_DIR)):
        if entry.lower().endswith(VIDEO_EXT) and os.path.isfile(os.path.join(VIDEO_DIR, entry)):
            files.append(entry)
    return files


def get_video_duration_seconds(video_path: str) -> Optional[float]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    raw_value = result.stdout.strip()
    if not raw_value:
        return None

    try:
        duration = float(raw_value)
    except ValueError:
        return None

    if duration <= 0:
        return None
    return duration


def calculate_video_metrics(video_name: str) -> dict:
    video_path = os.path.join(VIDEO_DIR, video_name)
    file_size = os.path.getsize(video_path)
    total_packets = math.ceil(file_size / MAX_RTP_PAYLOAD) if file_size else 0
    total_header_bytes = total_packets * NETWORK_HEADER_BYTES

    metrics = {
        "video": video_name,
        "file_size_bytes": file_size,
        "payload_bytes_per_packet": MAX_RTP_PAYLOAD,
        "header_bytes_per_packet": NETWORK_HEADER_BYTES,
        "total_packets": total_packets,
        "total_header_bytes": total_header_bytes,
        "exclusive_data_bytes": file_size,
        "duration_seconds": None,
        "estimated_frames_30fps": None,
        "packets_per_frame_30fps": None,
        "tx_rate_bps_30fps": None,
        "tx_rate_mbps_30fps": None,
    }

    duration = get_video_duration_seconds(video_path)
    if duration is None:
        return metrics

    estimated_frames = duration * 30.0
    packets_per_frame = (total_packets / estimated_frames) if estimated_frames > 0 else 0.0
    packets_per_second = packets_per_frame * 30.0
    tx_rate_bps = packets_per_second * (MAX_RTP_PAYLOAD + NETWORK_HEADER_BYTES) * 8

    metrics["duration_seconds"] = round(duration, 3)
    metrics["estimated_frames_30fps"] = round(estimated_frames, 3)
    metrics["packets_per_frame_30fps"] = round(packets_per_frame, 6)
    metrics["tx_rate_bps_30fps"] = round(tx_rate_bps, 3)
    metrics["tx_rate_mbps_30fps"] = round(tx_rate_bps / 1_000_000.0, 6)
    return metrics


def generate_metrics_report() -> list[dict]:
    report = []
    for video_name in list_videos():
        report.append(calculate_video_metrics(video_name))

    with open(METRICS_FILE, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    return report


def send_metrics(sender: socket.socket, client_ip: str, client_port: int) -> None:
    videos = list_videos()
    if not videos:
        send_control(sender, client_ip, client_port, "ERR|Nenhum video .ts para gerar metricas")
        return

    report = generate_metrics_report()
    send_control(sender, client_ip, client_port, f"METRICS_FILE|{os.path.basename(METRICS_FILE)}")

    for entry in report:
        summary = (
            "METRIC|"
            f"video={entry['video']};"
            f"packets={entry['total_packets']};"
            f"header_bpp={entry['header_bytes_per_packet']};"
            f"data_bytes={entry['exclusive_data_bytes']};"
            f"ppf30={entry['packets_per_frame_30fps']};"
            f"tx_mbps30={entry['tx_rate_mbps_30fps']}"
        )
        send_control(sender, client_ip, client_port, summary)


def send_control(sender: socket.socket, client_ip: str, client_port: int, message: str) -> None:
    payload = f"CTRL|{message}".encode("utf-8")
    pkt = build_udp_packet(SERVER_IP, client_ip, SERVER_PORT, client_port, payload)
    sender.sendto(pkt, (client_ip, 0))


def send_catalog(sender: socket.socket, client_ip: str, client_port: int) -> None:
    videos = list_videos()
    if not videos:
        send_control(sender, client_ip, client_port, "ERR|Nenhum video .ts encontrado em servidor/videos")
        return

    if len(videos) < 3:
        send_control(sender, client_ip, client_port, "WARN|Catalogo possui menos de 3 videos")

    send_control(sender, client_ip, client_port, "CATALOG|" + ",".join(videos))


def start_streaming(sender: socket.socket, client_ip: str, client_port: int, video_name: str) -> None:
    videos = list_videos()
    if video_name not in videos:
        send_control(sender, client_ip, client_port, f"ERR|Video nao encontrado: {video_name}")
        return

    video_path = os.path.join(VIDEO_DIR, video_name)
    send_control(sender, client_ip, client_port, f"START|{video_name}\nStreaming em andamento...")

    sequence = 0
    timestamp = 0
    sleep_interval = 1.0 / PACKETS_PER_SECOND

    with open(video_path, "rb") as fh:
        while True:
            chunk = fh.read(MAX_RTP_PAYLOAD)
            if not chunk:
                break

            marker = 0
            if len(chunk) < MAX_RTP_PAYLOAD:
                marker = 1

            rtp_payload = build_rtp_packet(sequence, timestamp, marker, chunk)
            pkt = build_udp_packet(SERVER_IP, client_ip, SERVER_PORT, client_port, rtp_payload)
            sender.sendto(pkt, (client_ip, 0))

            sequence = (sequence + 1) & 0xFFFF
            timestamp = (timestamp + 3000) & 0xFFFFFFFF
            time.sleep(sleep_interval)

    send_control(sender, client_ip, client_port, f"END|{video_name}")


def handle_command(sender: socket.socket, client_ip: str, client_port: int, command: str) -> None:
    command = command.strip()
    if not command:
        return

    # Ignora entradas fora do conjunto esperado de comandos textuais.
    if len(command) > 256:
        send_control(sender, client_ip, client_port, "ERR|Comando muito longo")
        return

    if command == "catalog":
        send_catalog(sender, client_ip, client_port)
        return

    if command == "metrics":
        send_metrics(sender, client_ip, client_port)
        return

    if command.startswith("stream "):
        parts = command.split(maxsplit=1)
        if len(parts) != 2 or not parts[1].strip():
            send_control(sender, client_ip, client_port, "ERR|Uso: stream <nome_video.ts>")
            return
        start_streaming(sender, client_ip, client_port, parts[1].strip())
        return

    send_control(sender, client_ip, client_port, "ERR|Comando invalido. Use: catalog, metrics ou stream <nome_video.ts>")


def start_server() -> None:
    sender = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW)
    sender.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)

    sniffer = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.ntohs(3))
    sniffer.bind((INTERFACE, 0))

    print(f"[+] Servidor raw socket em {SERVER_IP}:{SERVER_PORT} na interface {INTERFACE}")
    print(f"[+] Pasta de videos: {VIDEO_DIR}")
    print("[+] Comandos suportados: catalog | metrics | stream <nome_video.ts>")

    try:
        while True:
            raw_packet, _ = sniffer.recvfrom(BUFFER_SIZE)
            parsed = parse_udp_from_raw(raw_packet)
            if parsed is None:
                continue

            if parsed["dst_ip"] != SERVER_IP or parsed["dst_port"] != SERVER_PORT:
                continue

            if parsed["src_ip"] != CLIENT_IP:
                continue

            payload = parsed["payload"]
            if not payload:
                continue

            try:
                command = payload.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                continue

            print(f"[>] Comando recebido de {parsed['src_ip']}:{parsed['src_port']}: {command}")
            handle_command(sender, parsed["src_ip"], parsed["src_port"], command)

    except KeyboardInterrupt:
        print("\n[!] Servidor interrompido")
    finally:
        sender.close()
        sniffer.close()


if __name__ == "__main__":
    start_server()