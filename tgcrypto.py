"""
Pure Python fallback for tgcrypto using cryptography library
"""
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

def ige256_encrypt(data, key, iv) -> bytes:
    data = bytes(data)
    key = bytes(key)
    iv = bytes(iv)
    pad_len = (16 - (len(data) % 16)) % 16
    if pad_len > 0:
        data = data + (b"\x00" * pad_len)
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    encryptor = cipher.encryptor()
    iv1, iv2 = bytearray(iv[:16]), bytearray(iv[16:32])
    res = bytearray()
    for i in range(0, len(data), 16):
        block = data[i:i+16]
        x = bytes(a ^ b for a, b in zip(block, iv1))
        c = bytes(a ^ b for a, b in zip(encryptor.update(x), iv2))
        res.extend(c)
        iv1, iv2 = c, block
    return bytes(res)

def ige256_decrypt(data, key, iv) -> bytes:
    data = bytes(data)
    key = bytes(key)
    iv = bytes(iv)
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    decryptor = cipher.decryptor()
    iv1, iv2 = bytearray(iv[:16]), bytearray(iv[16:32])
    res = bytearray()
    for i in range(0, len(data), 16):
        block = data[i:i+16]
        x = bytes(a ^ b for a, b in zip(block, iv2))
        p = bytes(a ^ b for a, b in zip(decryptor.update(x), iv1))
        res.extend(p)
        iv1, iv2 = block, p
    return bytes(res)
