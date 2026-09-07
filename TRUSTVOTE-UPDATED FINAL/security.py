import os
import io
import json
import base64
import hashlib
from PIL import Image

SECRET_KEY = b"trustvote_secure_crypto_key_2026_goi"

def compress_photo_to_jpeg(photo_path, max_size=36):
    """Resizes a voter's photo to max_size x max_size and compresses it heavily to fit in a QR code."""
    try:
        if not os.path.exists(photo_path):
            print(f"[Security] Image path not found: {photo_path}")
            return b""
            
        import cv2
        from utils.face import extract_face_roi
        
        img_bgr = cv2.imread(photo_path)
        if img_bgr is None:
            return b""
            
        # Crop the face region to save storage space
        face_roi = extract_face_roi(img_bgr)
        if face_roi is not None:
            img_bgr = face_roi
            
        # Convert BGR to RGB for PIL Image processing
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(img_rgb)
        img = img.resize((max_size, max_size))
        
        out_buf = io.BytesIO()
        img.save(out_buf, format='JPEG', quality=15)
        return out_buf.getvalue()
    except Exception as e:
        print(f"[Security] Photo compression error: {e}")
        return b""

def xor_crypt(data: bytes, key: bytes) -> bytes:
    """SHA256-CTR custom stream cipher (pure Python, dependency-free)."""
    out = bytearray()
    counter = 0
    while len(out) < len(data):
        block_key = hashlib.sha256(key + str(counter).encode()).digest()
        needed = min(len(data) - len(out), 32)
        for i in range(needed):
            out.append(data[len(out)] ^ block_key[i])
        counter += 1
    return bytes(out)

def encrypt_voter_data(vid, name, dob, gender, photo_path):
    """Encrypts voter details and compressed face photo into a Base64 token for QR codes."""
    # 1. Compress photo to raw JPEG bytes (extremely compact)
    face_bytes = compress_photo_to_jpeg(photo_path)
    
    # 2. Build binary payload (delimiter separated to avoid JSON overhead)
    meta = f"{vid}|{name}|{dob}|{gender}|".encode('utf-8')
    payload = meta + face_bytes
    
    # 3. Create cryptographic SHA256 signature to prevent tampering
    signature = hashlib.sha256(SECRET_KEY + payload).digest()
    
    # 4. Pack signature + payload
    packed = signature + payload
    
    # 5. Encrypt
    ciphertext = xor_crypt(packed, SECRET_KEY)
    
    # 6. Base64 encode for string QR payload
    return base64.b64encode(ciphertext).decode('utf-8')

def decrypt_voter_data(encrypted_str):
    """Decrypts a QR token, verifies its cryptographic signature, and returns the voter details."""
    try:
        # 1. Decode base64
        ciphertext = base64.b64decode(encrypted_str)
        
        # 2. Decrypt
        decrypted = xor_crypt(ciphertext, SECRET_KEY)
        
        # 3. Unpack signature (first 32 bytes) and payload
        if len(decrypted) < 32:
            return None
            
        sig = decrypted[:32]
        payload = decrypted[32:]
        
        # 4. Verify signature
        expected_sig = hashlib.sha256(SECRET_KEY + payload).digest()
        if sig != expected_sig:
            print("[Security] Signature mismatch! Invalid QR code token.")
            return None
            
        # 5. Parse metadata using delimiters
        parts = []
        start = 0
        for _ in range(4):
            idx = payload.find(b'|', start)
            if idx == -1:
                return None
            parts.append(payload[start:idx].decode('utf-8'))
            start = idx + 1
            
        vid, name, dob, gender = parts
        face_bytes = payload[start:]
        
        return {
            "v_id": vid,
            "name": name,
            "dob": dob,
            "gender": gender,
            "face_bytes": face_bytes
        }
    except Exception as e:
        print(f"[Security] Decryption failed: {e}")
        return None
