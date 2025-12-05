import base64


def encode_b64(s: str) -> str:
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


def decode_b64(s: str) -> str:
    return base64.b64decode(s.encode("ascii")).decode("utf-8")
