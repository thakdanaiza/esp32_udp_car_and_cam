#!/usr/bin/env python3
"""
UDP communication test with ESP32.
- Sends a ping to ESP32 every second
- Receives echo + heartbeat from ESP32
"""

import socket
import threading
import time

ESP32_IP      = "192.168.1.31"  # <-- Enter the IP address of the ESP32
UDP_SEND_PORT = 5005            # port that ESP32 receives on
UDP_RECV_PORT = 5006            # port that PC receives on

def recv_thread(sock):
    """Receive packets from ESP32"""
    while True:
        try:
            data, addr = sock.recvfrom(256)
            print(f"[RX] from {addr[0]}  \"{data.decode(errors='ignore')}\"")
        except socket.timeout:
            pass
        except Exception as e:
            print(f"[RX ERROR] {e}")

def main():
    print("=== UDP Test ===")
    print(f"ESP32  : {ESP32_IP}:{UDP_SEND_PORT}")
    print(f"PC recv: port {UDP_RECV_PORT}")
    print("Press Ctrl+C to stop.\n")

    # Socket for sending
    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Socket for receiving
    recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    recv_sock.bind(("", UDP_RECV_PORT))
    recv_sock.settimeout(1.0)

    # Start receive thread
    t = threading.Thread(target=recv_thread, args=(recv_sock,), daemon=True)
    t.start()

    counter = 0
    try:
        while True:
            msg = f"PING:{counter}"
            send_sock.sendto(msg.encode(), (ESP32_IP, UDP_SEND_PORT))
            print(f"[TX] \"{msg}\" → {ESP32_IP}:{UDP_SEND_PORT}")
            counter += 1
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        send_sock.close()
        recv_sock.close()

if __name__ == "__main__":
    main()
