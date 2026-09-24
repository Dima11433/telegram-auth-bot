import os
import io
import time
import shutil
import struct
import hashlib
import zipfile
import sqlite3
import logging
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

logger = logging.getLogger(__name__)

# Standard Telegram Datacenter IP Addresses
DC_IPS = {
    1: "149.154.175.53",
    2: "149.154.167.51",
    3: "149.154.175.100",
    4: "149.154.167.91",
    5: "91.108.56.130"
}

# --- Cryptographic Helpers (AES-IGE & Hashes) ---

def aes_ige_encrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    """Encrypts data using AES-256 in IGE (Infinite Garble Extension) mode."""
    # Ensure data length is a multiple of 16
    pad_len = (16 - (len(data) % 16)) % 16
    if pad_len > 0:
        data = data + (b"\x00" * pad_len)

    cipher = Cipher(algorithms.AES(key), modes.ECB())
    encryptor = cipher.encryptor()
    iv1, iv2 = iv[:16], iv[16:32]
    res = bytearray()
    for i in range(0, len(data), 16):
        block = data[i:i+16]
        x = bytes(a ^ b for a, b in zip(block, iv1))
        c = bytes(a ^ b for a, b in zip(encryptor.update(x), iv2))
        res.extend(c)
        iv1, iv2 = c, block
    return bytes(res)


def aes_ige_decrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    """Decrypts data using AES-256 in IGE mode."""
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    decryptor = cipher.decryptor()
    iv1, iv2 = iv[:16], iv[16:32]
    res = bytearray()
    for i in range(0, len(data), 16):
        block = data[i:i+16]
        x = bytes(a ^ b for a, b in zip(block, iv2))
        p = bytes(a ^ b for a, b in zip(decryptor.update(x), iv1))
        res.extend(p)
        iv1, iv2 = block, p
    return bytes(res)


def _tdf_pack(data: bytes, key: bytes, iv: bytes, version: int = 1009000) -> bytes:
    """Packs raw bytes into a Telegram Desktop TDF$ container."""
    # Telegram Desktop TDF structure:
    # 4 bytes magic: 'TDF$'
    # 4 bytes version (Big Endian)
    # Encrypted data (AES-IGE)
    # 16 bytes MD5 checksum of (decrypted_data + len + version + magic)
    magic = b"TDF$"
    ver_bytes = struct.pack(">I", version)
    len_bytes = struct.pack(">I", len(data))
    
    # Calculate MD5 checksum
    md5_ctx = hashlib.md5()
    md5_ctx.update(data)
    md5_ctx.update(len_bytes)
    md5_ctx.update(ver_bytes)
    md5_ctx.update(magic)
    checksum = md5_ctx.digest()

    encrypted_data = aes_ige_encrypt(data, key, iv)
    return magic + ver_bytes + encrypted_data + checksum


def _tdf_unpack(raw_file_bytes: bytes, key: bytes, iv: bytes) -> Tuple[bool, Optional[bytes], int]:
    """Unpacks a Telegram Desktop TDF$ container and verifies MD5 checksum."""
    if len(raw_file_bytes) < 24 or not raw_file_bytes.startswith(b"TDF$"):
        return False, None, 0

    magic = raw_file_bytes[:4]
    version = struct.unpack(">I", raw_file_bytes[4:8])[0]
    checksum = raw_file_bytes[-16:]
    encrypted_data = raw_file_bytes[8:-16]

    decrypted = aes_ige_decrypt(encrypted_data, key, iv)

    # Validate MD5 if possible (try exact length matching)
    # Many versions pad or have trailing bytes
    # Try multiple lengths if exact match differs
    for data_len in range(len(decrypted), max(0, len(decrypted) - 16), -1):
        candidate = decrypted[:data_len]
        len_bytes = struct.pack(">I", data_len)
        md5_ctx = hashlib.md5()
        md5_ctx.update(candidate)
        md5_ctx.update(len_bytes)
        md5_ctx.update(struct.pack(">I", version))
        md5_ctx.update(magic)
        if md5_ctx.digest() == checksum:
            return True, candidate, version

    # Fallback return full decrypted block if magic was correct
    return True, decrypted, version


# --- Telethon SQLite Session Helpers ---

def create_telethon_session_file(
    session_path: Path,
    dc_id: int,
    auth_key_bytes: bytes,
    port: int = 443
) -> None:
    """Creates a standard Telethon SQLite .session file from dc_id and auth_key."""
    ip = DC_IPS.get(dc_id, "149.154.167.51")
    if session_path.exists():
        try:
            session_path.unlink()
        except Exception:
            pass

    conn = sqlite3.connect(session_path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS version (version integer)")
    cur.execute("DELETE FROM version")
    cur.execute("INSERT INTO version VALUES (7)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            dc_id integer primary key,
            server_address text,
            port integer,
            auth_key blob,
            takeout_id integer
        )
    """)
    cur.execute("DELETE FROM sessions")
    cur.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?)", (dc_id, ip, port, auth_key_bytes, None))

    cur.execute("""
        CREATE TABLE IF NOT EXISTS entities (
            id integer primary key,
            hash integer not null,
            username text,
            phone integer,
            name text,
            date integer
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sent_files (
            md5_digest blob,
            file_size integer,
            type integer,
            id integer,
            hash integer,
            primary key(md5_digest, file_size, type)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS update_state (
            id integer primary key,
            pts integer,
            qts integer,
            seq integer,
            date integer,
            unread_count integer
        )
    """)
    conn.commit()
    conn.close()


def extract_auth_key_from_session_file(session_path: Path) -> Tuple[int, bytes]:
    """Reads DC ID and 256-byte Auth Key from a Telethon .session SQLite file."""
    if not session_path.exists():
        raise FileNotFoundError(f"Session file not found: {session_path}")

    conn = sqlite3.connect(session_path)
    cur = conn.cursor()
    cur.execute("SELECT dc_id, auth_key FROM sessions LIMIT 1")
    row = cur.fetchone()
    conn.close()

    if not row or not row[1] or len(row[1]) != 256:
        raise ValueError("Invalid or corrupted session database (AuthKey must be 256 bytes)")

    return int(row[0]), bytes(row[1])


# --- TData Reader / Parser ---

class QDataStreamReader:
    """Helper to parse Qt QDataStream binary serializations."""
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def read_uint32(self) -> int:
        if self.pos + 4 > len(self.data):
            return 0
        val = struct.unpack(">I", self.data[self.pos:self.pos+4])[0]
        self.pos += 4
        return val

    def read_int32(self) -> int:
        if self.pos + 4 > len(self.data):
            return 0
        val = struct.unpack(">i", self.data[self.pos:self.pos+4])[0]
        self.pos += 4
        return val

    def read_uint64(self) -> int:
        if self.pos + 8 > len(self.data):
            return 0
        val = struct.unpack(">Q", self.data[self.pos:self.pos+8])[0]
        self.pos += 8
        return val

    def read_bytes(self, length: int) -> bytes:
        if self.pos + length > len(self.data):
            res = self.data[self.pos:]
            self.pos = len(self.data)
            return res
        res = self.data[self.pos:self.pos+length]
        self.pos += length
        return res

    def read_byte_array(self) -> bytes:
        length = self.read_uint32()
        if length == 0xFFFFFFFF or length == 0:
            return b""
        return self.read_bytes(length)


def parse_tdata_folder(tdata_dir: Path, passcode: bytes = b"") -> Tuple[int, bytes, Optional[int]]:
    """
    Parses a Telegram Desktop `tdata` folder and extracts (dc_id, auth_key, user_id).
    Supports all Telegram Desktop versions and account map structures.
    """
    if not tdata_dir.is_dir():
        raise FileNotFoundError(f"Tdata directory not found: {tdata_dir}")

    # 1. Locate key_datas file
    key_file = tdata_dir / "key_datas"
    if not key_file.exists():
        key_file = tdata_dir / "key_data"
    if not key_file.exists():
        # Search in subfolders
        found_keys = list(tdata_dir.glob("**/key_data*"))
        if found_keys:
            key_file = found_keys[0]
        else:
            raise FileNotFoundError("Could not find 'key_datas' in tdata directory")

    raw_key_data = key_file.read_bytes()
    if len(raw_key_data) < 304: # 4 (magic) + 4 (ver) + 32 (salt) + 256 (key) + 16 (info) + 16 (md5) = 328
        # Some older formats don't have TDF$ header on key_data
        salt = raw_key_data[:32]
        key_enc = raw_key_data[32:288]
    else:
        # TDF$ container or raw payload
        if raw_key_data.startswith(b"TDF$"):
            salt = raw_key_data[8:40]
            key_enc = raw_key_data[40:296]
        else:
            salt = raw_key_data[:32]
            key_enc = raw_key_data[32:288]

    # 2. Derive decryption key from passcode (default empty)
    hash_val = hashlib.sha512(salt + passcode + salt).digest()
    key_aes = hash_val[:32]
    iv_aes = hash_val[32:64]

    local_key = aes_ige_decrypt(key_enc, key_aes, iv_aes)

    # 3. Locate and decrypt map files (D877F783D5D3EF8C* or maps*)
    map_candidates = []
    # Known default map file names
    for name in ["D877F783D5D3EF8Cs", "D877F783D5D3EF8C0", "D877F783D5D3EF8C1", "D877F783D5D3EF8C"]:
        p = tdata_dir / name
        if p.exists():
            map_candidates.append(p)

    # Check directory D877F783D5D3EF8C/maps or subfolders
    for sub in tdata_dir.glob("**/maps*"):
        map_candidates.append(sub)
    for sub in tdata_dir.glob("**/D877F783D5D3EF8C*"):
        if sub.is_file():
            map_candidates.append(sub)

    # Also add any files inside D877F783D5D3EF8C/
    account_dir = tdata_dir / "D877F783D5D3EF8C"
    if account_dir.is_dir():
        for f in account_dir.iterdir():
            if f.is_file():
                map_candidates.append(f)

    # Remove duplicates
    map_candidates = list(dict.fromkeys(map_candidates))

    if not map_candidates:
        # Search all files for potential TDF payload
        for f in tdata_dir.glob("*"):
            if f.is_file() and f.name not in ("key_datas", "key_data", "settingss", "shortcuts-default.json"):
                map_candidates.append(f)

    extracted_keys = []
    main_dc_id = 2
    user_id = None

    # Key for decrypting maps
    map_key = local_key[:32]
    map_iv = local_key[32:64]

    for map_file in map_candidates:
        try:
            content = map_file.read_bytes()
            if not content:
                continue

            decrypted_data = None
            if content.startswith(b"TDF$"):
                ok, dec, _ = _tdf_unpack(content, map_key, map_iv)
                if ok and dec:
                    decrypted_data = dec
            else:
                decrypted_data = aes_ige_decrypt(content, map_key, map_iv)

            if not decrypted_data:
                continue

            # Scan decrypted stream for 256-byte auth keys and DC IDs
            reader = QDataStreamReader(decrypted_data)
            
            # 1. Structured parse
            count = reader.read_uint32()
            if 0 < count < 50:
                for _ in range(count):
                    key_type = reader.read_uint32()
                    if key_type in (1, 0x1000): # dbiKey
                        dc = reader.read_uint32()
                        peek_len = reader.read_uint32()
                        if peek_len == 256:
                            auth = reader.read_bytes(256)
                        else:
                            # Not length-prefixed, reconstruct with peek_len bytes
                            len_bytes = struct.pack(">I", peek_len)
                            auth = len_bytes + reader.read_bytes(252)
                        if len(auth) == 256 and dc in (1, 2, 3, 4, 5) and auth != (b"\x00" * 256):
                            extracted_keys.append((dc, auth))
                    elif key_type in (2, 0x1001): # dbiUser
                        user_id = reader.read_uint64()
                    elif key_type in (3, 0x1002): # dbiDcId
                        main_dc_id = reader.read_uint32()

            # 2. Raw scan fallback: search for 256-byte blocks with matching DC byte
            if not extracted_keys:
                for offset in range(0, len(decrypted_data) - 260):
                    possible_dc = struct.unpack(">I", decrypted_data[offset:offset+4])[0]
                    if possible_dc in (1, 2, 3, 4, 5):
                        candidate_key = decrypted_data[offset+4 : offset+260]
                        if len(candidate_key) == 256 and candidate_key != (b"\x00" * 256):
                            extracted_keys.append((possible_dc, candidate_key))
                            main_dc_id = possible_dc
                            break

        except Exception as e:
            logger.debug(f"Parsing candidate map {map_file} failed: {e}")

    if not extracted_keys:
        raise ValueError("Could not extract MTProto AuthKey from Tdata (format unrecognized or corrupted)")

    # Select key matching main_dc_id or first valid
    selected_dc, selected_auth = extracted_keys[0]
    for dc, auth in extracted_keys:
        if dc == main_dc_id:
            selected_dc, selected_auth = dc, auth
            break

    return selected_dc, selected_auth, user_id


# --- TData Generator / Creator ---

def create_tdata_archive(
    dc_id: int,
    auth_key_bytes: bytes,
    output_zip_path: Path,
    user_id: int = 0
) -> Path:
    """
    Creates a valid, complete Telegram Desktop `tdata.zip` archive from an AuthKey and DC ID.
    Can be extracted directly into Telegram Desktop root folder.
    Supports all modern Telegram Desktop versions (4.x, 5.x) and legacy versions.
    """
    if len(auth_key_bytes) != 256:
        raise ValueError(f"AuthKey must be exactly 256 bytes (got {len(auth_key_bytes)})")

    # Generate master local key (256 bytes) and salt (32 bytes)
    local_key = os.urandom(256)
    salt = os.urandom(32)

    # Key encryption with empty passcode (default Telegram Desktop state)
    passcode = b""
    hash_val = hashlib.sha512(salt + passcode + salt).digest()
    key_aes = hash_val[:32]
    iv_aes = hash_val[32:64]

    key_enc = aes_ige_encrypt(local_key, key_aes, iv_aes)
    info_bytes = b"INFO" + os.urandom(12)
    info_enc = aes_ige_encrypt(info_bytes, local_key[:32], local_key[32:64])

    # 1. key_datas file payload
    key_datas_payload = salt + key_enc + info_enc
    magic = b"TDF$"
    ver_bytes = struct.pack(">I", 1009000)
    len_bytes = struct.pack(">I", len(key_datas_payload))
    md5_ctx = hashlib.md5()
    md5_ctx.update(key_datas_payload)
    md5_ctx.update(len_bytes)
    md5_ctx.update(ver_bytes)
    md5_ctx.update(magic)
    key_datas_file = magic + ver_bytes + key_datas_payload + md5_ctx.digest()

    # 2. Build account map stream
    # Qt serialized payload:
    # 3 items:
    # - Item 1: dbiKey (1) -> dc_id (quint32) + QByteArray(256, auth_key_bytes)
    # - Item 2: dbiUser (2) -> user_id (quint64)
    # - Item 3: dbiDcId (3) -> dc_id (quint32)
    map_stream = bytearray()
    map_stream.extend(struct.pack(">I", 3)) # 3 items
    
    # Item 1: AuthKey (dbiKey = 1)
    map_stream.extend(struct.pack(">I", 1))
    map_stream.extend(struct.pack(">I", dc_id))
    map_stream.extend(struct.pack(">I", 256)) # QByteArray length is 256 bytes!
    map_stream.extend(auth_key_bytes)

    # Item 2: User ID (dbiUser = 2)
    map_stream.extend(struct.pack(">I", 2))
    map_stream.extend(struct.pack(">Q", user_id if user_id else 123456789))

    # Item 3: Main DC (dbiDcId = 3)
    map_stream.extend(struct.pack(">I", 3))
    map_stream.extend(struct.pack(">I", dc_id))

    map_key = local_key[:32]
    map_iv = local_key[32:64]
    map_file_bytes = _tdf_pack(bytes(map_stream), map_key, map_iv)

    # 3. Build subfolder D877F783D5D3EF8C/data
    data_stream = bytearray()
    data_stream.extend(struct.pack(">I", 1)) # 1 item
    data_stream.extend(struct.pack(">I", 1)) # dbiKey
    data_stream.extend(struct.pack(">I", dc_id))
    data_stream.extend(struct.pack(">I", 256))
    data_stream.extend(auth_key_bytes)
    data_file_bytes = _tdf_pack(bytes(data_stream), map_key, map_iv)

    # 4. Settings file
    settings_stream = bytearray()
    settings_stream.extend(struct.pack(">I", 0)) # 0 items (default settings)
    settings_file_bytes = _tdf_pack(bytes(settings_stream), map_key, map_iv)

    # 5. Multi-account root map for modern Telegram Desktop
    # D877F783D5D3EF8C is md5("data")[:16].upper()
    acc_key_str = b"D877F783D5D3EF8C"
    root_map_stream = bytearray()
    root_map_stream.extend(struct.pack(">I", 2)) # 2 items
    # dbiAccountOrder (0x0002)
    root_map_stream.extend(struct.pack(">I", 0x0002))
    root_map_stream.extend(struct.pack(">I", 1)) # 1 account
    root_map_stream.extend(struct.pack(">I", len(acc_key_str)))
    root_map_stream.extend(acc_key_str)
    # dbiAccounts (0x0001)
    root_map_stream.extend(struct.pack(">I", 0x0001))
    root_map_stream.extend(struct.pack(">I", 1)) # 1 account
    root_map_stream.extend(struct.pack(">I", len(acc_key_str)))
    root_map_stream.extend(acc_key_str)
    root_map_stream.extend(struct.pack(">I", 0)) # index 0
    root_map_file_bytes = _tdf_pack(bytes(root_map_stream), map_key, map_iv)

    # Write ZIP archive
    output_zip_path = Path(output_zip_path).resolve()
    output_zip_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Standard root folder 'tdata/'
        zf.writestr("tdata/key_datas", key_datas_file)
        zf.writestr("tdata/key_data", key_datas_file)
        zf.writestr("tdata/D877F783D5D3EF8Cs", map_file_bytes)
        zf.writestr("tdata/D877F783D5D3EF8C0", map_file_bytes)
        zf.writestr("tdata/D877F783D5D3EF8C1", map_file_bytes)
        zf.writestr("tdata/D877F783D5D3EF8C/maps", map_file_bytes)
        zf.writestr("tdata/D877F783D5D3EF8C/maps0", map_file_bytes)
        zf.writestr("tdata/D877F783D5D3EF8C/data", data_file_bytes)
        zf.writestr("tdata/D877F783D5D3EF8C/data0", data_file_bytes)
        zf.writestr("tdata/settingss", settings_file_bytes)
        zf.writestr("tdata/settings0", settings_file_bytes)

    return output_zip_path


# --- High Level Endpoints ---

def convert_tdata_zip_to_session_file(
    zip_source: Any, # Path, str, or bytes
    destination_session_path: Path
) -> Tuple[bool, int, str]:
    """
    Extracts a ZIP containing a Tdata folder and converts it to a Telethon .session file.
    Returns (success, dc_id, error_message).
    """
    import tempfile
    temp_dir = Path(tempfile.mkdtemp(prefix="tdata_conv_"))
    try:
        if isinstance(zip_source, (str, Path)):
            with zipfile.ZipFile(zip_source, "r") as zf:
                zf.extractall(temp_dir)
        elif isinstance(zip_source, (bytes, io.BytesIO)):
            bio = zip_source if isinstance(zip_source, io.BytesIO) else io.BytesIO(zip_source)
            with zipfile.ZipFile(bio, "r") as zf:
                zf.extractall(temp_dir)
        else:
            return False, 0, "Unsupported ZIP source format"

        # Search for tdata folder or key_datas
        tdata_path = temp_dir
        if (temp_dir / "tdata").is_dir():
            tdata_path = temp_dir / "tdata"
        else:
            subdirs = list(temp_dir.glob("**/tdata"))
            if subdirs:
                tdata_path = subdirs[0]
            else:
                key_files = list(temp_dir.glob("**/key_data*"))
                if key_files:
                    tdata_path = key_files[0].parent

        dc_id, auth_key, _ = parse_tdata_folder(tdata_path)
        create_telethon_session_file(destination_session_path, dc_id, auth_key)
        return True, dc_id, "OK"
    except Exception as e:
        logger.error(f"Error converting Tdata ZIP to session: {e}")
        return False, 0, str(e)
    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


def export_session_to_tdata_zip(
    session_path: Path,
    output_zip_path: Path,
    user_id: int = 0
) -> Tuple[bool, str]:
    """
    Exports a Telethon .session file into a Telegram Desktop ready tdata.zip archive.
    """
    try:
        dc_id, auth_key = extract_auth_key_from_session_file(session_path)
        
        # If user_id wasn't provided, read authentic tg_user_id from the session SQLite database
        if not user_id:
            try:
                conn = sqlite3.connect(session_path)
                cur = conn.cursor()
                row = cur.execute("SELECT id FROM entities WHERE id > 0 AND id != 777000 LIMIT 1").fetchone()
                if row and row[0]:
                    user_id = int(row[0])
                conn.close()
            except Exception:
                pass

        create_tdata_archive(dc_id, auth_key, output_zip_path, user_id=user_id)
        return True, "OK"
    except Exception as e:
        logger.error(f"Error exporting session to Tdata: {e}")
        return False, str(e)
