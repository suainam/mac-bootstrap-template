#!/usr/bin/env python3
import socket, sys, select, os

host = sys.argv[1]
port = int(sys.argv[2])

proxy_port = int(os.environ.get('MAC_BOOTSTRAP_SSH_PROXY_PORT', '7897'))
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(15)
s.connect(('127.0.0.1', proxy_port))

s.send(f'CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n'.encode())
resp = s.recv(4096)
if b'200' not in resp.split(b'\r\n')[0]:
    sys.exit(1)

s.setblocking(False)
while True:
    r, _, _ = select.select([sys.stdin, s], [], [])
    if s in r:
        try:
            data = s.recv(65536)
            if not data:
                break
            os.write(1, data)
        except:
            break
    if sys.stdin in r:
        try:
            data = os.read(0, 65536)
            if not data:
                s.shutdown(socket.SHUT_WR)
                continue
            s.send(data)
        except:
            break
