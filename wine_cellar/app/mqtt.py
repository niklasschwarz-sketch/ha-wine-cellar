"""A very small MQTT 3.1.1 publisher, standard library only.

It opens a connection, sends a list of messages (QoS 0), asks the broker to answer a ping so it is sure
the broker has taken everything, and closes again. That is all the add-on needs to tell Home Assistant
about the cellar. It never subscribes and never keeps a connection open.
"""
import socket
import ssl


class MqttError(Exception):
    pass


def _varlen(n):
    out = bytearray()
    while True:
        d, n = n % 128, n // 128
        out.append(d | (128 if n else 0))
        if not n:
            return bytes(out)


def _str(s):
    b = s.encode("utf-8")
    return len(b).to_bytes(2, "big") + b


def _read(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise MqttError("The broker closed the connection")
        buf += chunk
    return buf


def _packet(sock):
    first = _read(sock, 1)[0]
    mult, length = 1, 0
    for _ in range(4):
        d = _read(sock, 1)[0]
        length += (d & 127) * mult
        mult *= 128
        if not d & 128:
            break
    return first, (_read(sock, length) if length else b"")


CONNACK_TEXT = {1: "unsupported protocol", 2: "client id refused", 3: "broker unavailable", 4: "wrong user name or password", 5: "not allowed"}


def publish_all(host, port, messages, user="", password="", use_ssl=False, client_id="wine_cellar", timeout=8):
    """messages: a list of (topic, payload, retain). Raises MqttError with a short, safe text."""
    try:
        sock = socket.create_connection((host, int(port)), timeout=timeout)
    except OSError as e:
        raise MqttError("Cannot reach the MQTT broker at %s:%s (%s)" % (host, port, type(e).__name__))
    try:
        sock.settimeout(timeout)
        if use_ssl:
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
        flags = 0x02  # clean session
        body = _str(client_id)
        if user:
            flags |= 0x80
            body += _str(user)
            if password:
                flags |= 0x40
                body += _str(password)
        head = _str("MQTT") + b"\x04" + bytes([flags]) + (30).to_bytes(2, "big")
        sock.sendall(b"\x10" + _varlen(len(head) + len(body)) + head + body)
        kind, data = _packet(sock)
        if kind >> 4 != 2 or len(data) < 2:
            raise MqttError("The broker did not answer like an MQTT broker")
        if data[1] != 0:
            raise MqttError("The broker refused the connection: " + CONNACK_TEXT.get(data[1], "code %d" % data[1]))
        for topic, payload, retain in messages:
            p = payload if isinstance(payload, bytes) else str(payload).encode("utf-8")
            rest = _str(topic) + p
            sock.sendall(bytes([0x30 | (1 if retain else 0)]) + _varlen(len(rest)) + rest)
        sock.sendall(b"\xc0\x00")  # ping: the answer comes after everything above has been handled
        kind, _ = _packet(sock)
        if kind >> 4 != 13:
            raise MqttError("The broker did not confirm the messages")
        try:
            sock.sendall(b"\xe0\x00")
        except OSError:
            pass
    except (OSError, ssl.SSLError) as e:
        raise MqttError("The connection to the MQTT broker failed (%s)" % type(e).__name__)
    finally:
        try:
            sock.close()
        except OSError:
            pass
