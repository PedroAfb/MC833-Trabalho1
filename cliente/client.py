import os
import socket
import struct
import time
from typing import Optional

CLIENT_IP = os.getenv("CLIENT_IP", "10.0.2.2")
CLIENT_PORT = int(os.getenv("CLIENT_PORT", "12345"))
SERVER_IP = os.getenv("SERVER_IP", "10.0.1.2")
SERVER_PORT = int(os.getenv("SERVER_PORT", "9999"))
INTERFACE = os.getenv("INTERFACE", "eth0")
BUFFER_SIZE = 65535

IP_FORMAT = "!BBHHHBBH4s4s"
UDP_FORMAT = "!HHHH"
RTP_FORMAT = "!BBHII"

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "downloads")

RTP_VERSION = 2
RTP_HEADER_SIZE = 12
RTP_PT_MPEG_TS = 33
STREAM_IDLE_TIMEOUT = 5.0


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

    if len(raw_packet) >= 34 and raw_packet[12:14] == b"\x08\x00":
        return 14

    if (raw_packet[0] >> 4) == 4:
        return 0

    return None


def parse_udp_from_raw(raw_packet: bytes) -> Optional[dict]:
    ip_offset = get_ip_offset(raw_packet)
    if ip_offset is None or len(raw_packet) < ip_offset + 28:
        return None

    iph = struct.unpack(IP_FORMAT, raw_packet[ip_offset : ip_offset + 20])
    ihl = (iph[0] & 0x0F) * 4
    protocol = iph[6]
    if protocol != socket.IPPROTO_UDP:
        return None

    src_ip = socket.inet_ntoa(iph[8])
    dst_ip = socket.inet_ntoa(iph[9])

    udp_start = ip_offset + ihl
    if len(raw_packet) < udp_start + 8:
        return None

    src_port, dst_port, udp_len, _ = struct.unpack(UDP_FORMAT, raw_packet[udp_start : udp_start + 8])
    payload_start = udp_start + 8
    payload_end = payload_start + max(0, udp_len - 8)

    return {
        "src_ip": src_ip,
        "dst_ip": dst_ip,
        "src_port": src_port,
        "dst_port": dst_port,
        "payload": raw_packet[payload_start:payload_end],
    }


def parse_rtp(packet: bytes) -> Optional[dict]:
    if len(packet) < RTP_HEADER_SIZE:
        return None

    b0, b1, seq, ts, ssrc = struct.unpack(RTP_FORMAT, packet[:RTP_HEADER_SIZE])
    version = (b0 >> 6) & 0x03
    if version != RTP_VERSION:
        return None

    marker = (b1 >> 7) & 0x01
    payload_type = b1 & 0x7F

    return {
        "sequence": seq,
        "timestamp": ts,
        "ssrc": ssrc,
        "marker": marker,
        "payload_type": payload_type,
        "payload": packet[RTP_HEADER_SIZE:],
    }


def send_command(sender: socket.socket, command: str) -> None:
    pkt = build_udp_packet(CLIENT_IP, SERVER_IP, CLIENT_PORT, SERVER_PORT, command.encode("utf-8"))
    sender.sendto(pkt, (SERVER_IP, 0))


def wait_control(sniffer: socket.socket, timeout_seconds: float = 3.0) -> Optional[str]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        sniffer.settimeout(max(0.1, deadline - time.time()))
        try:
            raw_packet, _ = sniffer.recvfrom(BUFFER_SIZE)
        except socket.timeout:
            continue

        parsed = parse_udp_from_raw(raw_packet)
        if parsed is None:
            continue

        if parsed["src_ip"] != SERVER_IP or parsed["dst_ip"] != CLIENT_IP:
            continue
        if parsed["src_port"] != SERVER_PORT or parsed["dst_port"] != CLIENT_PORT:
            continue

        payload = parsed["payload"]
        if payload.startswith(b"CTRL|"):
            return payload.decode("utf-8", errors="ignore")
    return None


def receive_stream(sniffer: socket.socket, video_name: str) -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, f"received_{video_name}")

    print(f"[-] Aguardando START para {video_name}...")

    # Espera o START antes de abrir o arquivo de saida.
    sniffer.settimeout(STREAM_IDLE_TIMEOUT)
    while True:
        try:
            raw_packet, _ = sniffer.recvfrom(BUFFER_SIZE)
        except socket.timeout:
            print("[!] Timeout aguardando inicio do stream")
            return
        parsed = parse_udp_from_raw(raw_packet)
        if parsed is None:
            continue
        if parsed["src_ip"] != SERVER_IP or parsed["dst_ip"] != CLIENT_IP:
            continue
        if parsed["src_port"] != SERVER_PORT or parsed["dst_port"] != CLIENT_PORT:
            continue

        payload = parsed["payload"]
        if payload.startswith(b"CTRL|START|"):
            print(payload.decode("utf-8", errors="ignore"))
            break
        if payload.startswith(b"CTRL|ERR|"):
            print(payload.decode("utf-8", errors="ignore"))
            return

    last_seq = None
    locked_ssrc = None
    total_packets = 0
    total_bytes = 0
    out_of_order = 0
    lost_packets_est = 0
    invalid_rtp = 0
    duplicate_packets = 0

    with open(output_path, "wb") as out:
        while True:
            try:
                raw_packet, _ = sniffer.recvfrom(BUFFER_SIZE)
            except socket.timeout:
                print("[!] Timeout durante stream, encerrando recepcao")
                break

            parsed = parse_udp_from_raw(raw_packet)
            if parsed is None:
                continue

            if parsed["src_ip"] != SERVER_IP or parsed["dst_ip"] != CLIENT_IP:
                continue
            if parsed["src_port"] != SERVER_PORT or parsed["dst_port"] != CLIENT_PORT:
                continue

            payload = parsed["payload"]
            if payload.startswith(b"CTRL|END|"):
                print(payload.decode("utf-8", errors="ignore"))
                break

            if payload.startswith(b"CTRL|"):
                print(payload.decode("utf-8", errors="ignore"))
                continue

            rtp = parse_rtp(payload)
            if rtp is None:
                invalid_rtp += 1
                continue

            if rtp["payload_type"] != RTP_PT_MPEG_TS:
                invalid_rtp += 1
                continue

            if locked_ssrc is None:
                locked_ssrc = rtp["ssrc"]
            elif rtp["ssrc"] != locked_ssrc:
                invalid_rtp += 1
                continue

            seq = rtp["sequence"]
            if last_seq is not None:
                expected = (last_seq + 1) & 0xFFFF
                if seq != expected:
                    if seq == last_seq:
                        duplicate_packets += 1
                        continue

                    delta = (seq - expected) & 0xFFFF
                    # Delta pequeno significa pacote adiantado (com perda no caminho).
                    if 0 < delta < 32768:
                        out_of_order += 1
                        lost_packets_est += delta
                        print(f"[!] Sequencia RTP adiantada: esperado={expected} recebido={seq}")
                    else:
                        # Pacote atrasado/antigo: descarta para nao corromper nem inflar o arquivo.
                        out_of_order += 1
                        print(f"[!] Sequencia RTP atrasada descartada: esperado={expected} recebido={seq}")
                        continue
            last_seq = seq

            data = rtp["payload"]
            out.write(data)
            total_packets += 1
            total_bytes += len(data)

    print(f"[+] Stream salvo em: {output_path}")
    print(f"[+] Pacotes RTP recebidos: {total_packets}")
    print(f"[+] Bytes de payload gravados: {total_bytes}")
    print(f"[+] Pacotes RTP invalidos: {invalid_rtp}")
    print(f"[+] Pacotes fora de ordem: {out_of_order}")
    print(f"[+] Duplicados descartados: {duplicate_packets}")
    print(f"[+] Perda estimada (seq): {lost_packets_est}")


def receive_metrics(sniffer: socket.socket, timeout_seconds: float = 3.0) -> None:
    deadline = time.time() + timeout_seconds
    print("[-] Aguardando metricas...")
    while time.time() < deadline:
        sniffer.settimeout(max(0.1, deadline - time.time()))
        try:
            raw_packet, _ = sniffer.recvfrom(BUFFER_SIZE)
        except socket.timeout:
            continue

        parsed = parse_udp_from_raw(raw_packet)
        if parsed is None:
            continue

        if parsed["src_ip"] != SERVER_IP or parsed["dst_ip"] != CLIENT_IP:
            continue
        if parsed["src_port"] != SERVER_PORT or parsed["dst_port"] != CLIENT_PORT:
            continue

        payload = parsed["payload"]
        if not payload.startswith(b"CTRL|"):
            continue

        msg = payload.decode("utf-8", errors="ignore")
        if "METRIC|" in msg or "METRICS_FILE|" in msg:
            print(f"[<] {msg}")


def start_client() -> None:
    sender = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW)
    sender.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)

    sniffer = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.ntohs(3))
    sniffer.bind((INTERFACE, 0))

    print("Aplicacao de Streaming (Client-Side)")
    print("- Digite catalog para listar videos")
    print("- Digite metrics para gerar metricas no servidor")
    print("- Digite stream <nome_video.ts> para receber stream")
    print("- Digite q para sair")

    try:
        while True:
            msg = input("\nCliente > ").strip()
            if msg == "q":
                break
            if not msg:
                continue

            if msg == "catalog":
                send_command(sender, msg)
                reply = wait_control(sniffer)
                if reply is None:
                    print("[!] Sem resposta do servidor para catalog")
                else:
                    print(f"[<] {reply}")
                continue

            if msg.startswith("stream "):
                parts = msg.split(maxsplit=1)
                if len(parts) != 2 or not parts[1].strip():
                    print("[!] Uso: stream <nome_video.ts>")
                    continue
                video_name = parts[1].strip()
                send_command(sender, msg)
                receive_stream(sniffer, video_name)
                continue

            if msg == "metrics":
                send_command(sender, msg)
                receive_metrics(sniffer, timeout_seconds=5.0)
                continue

            print("[!] Comando invalido. Use: catalog, metrics ou stream <nome_video.ts>")

    except KeyboardInterrupt:
        print("\n[!] Cliente interrompido")
    finally:
        sender.close()
        sniffer.close()


if __name__ == "__main__":
    start_client()