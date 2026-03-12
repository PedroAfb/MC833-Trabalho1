FROM ubuntu:22.04

RUN apt-get update && apt-get install -y mpv ffmpeg python3 python3-pip tcpdump iputils-ping iproute2 iputils-tracepath python3 python3-pip && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install numpy rich
WORKDIR /app