import os
import cv2
import numpy as np

try:
    from pyzbar.pyzbar import decode as zbar_decode
    HAS_PYZBAR = True
except Exception:
    HAS_PYZBAR = False

def decode_qr_from_image(image_bytes):
    """
    High-accuracy multi-engine QR code extractor:
    1. PyZBar + OpenCV hybrid decoding
    2. Multi-region crop (Full, Right Half, QR Pouch, Center Pass)
    3. Multi-scale super-resolution (1.0x, 2.0x, 3.0x, 1.5x)
    4. Contrast enhancement (CLAHE + Otsu Binarization)
    """
    if not image_bytes:
        return None

    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return None

    h, w = img.shape[:2]
    candidates = []

    # 1. Full image
    candidates.append(img)

    # 2. Right half (Dual-sided Voter Card back where QR code is printed)
    if w > 250:
        candidates.append(img[:, int(w * 0.42):])
        candidates.append(img[:, int(w * 0.48):])

    # 3. Dedicated QR pouch region (Top-Right / Center-Right)
    if w > 300 and h > 180:
        candidates.append(img[int(h * 0.05):int(h * 0.75), int(w * 0.45):int(w * 0.98)])
        candidates.append(img[int(h * 0.08):int(h * 0.65), int(w * 0.50):int(w * 0.95)])

    # 4. Center Crop (Voting Pass / Standalone QR card)
    candidates.append(img[int(h * 0.12):int(h * 0.88), int(w * 0.12):int(w * 0.88)])

    # Secondary detector
    cv_detector = cv2.QRCodeDetector()

    for cand in candidates:
        if cand is None or cand.size == 0:
            continue

        # Try multiple scales (crucial for dense 1KB+ encrypted voter QR codes)
        for scale in [1.0, 2.0, 3.0, 1.5, 0.75]:
            if scale == 1.0:
                scaled = cand
            else:
                scaled = cv2.resize(cand, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

            # Strategy A: Direct PyZBar
            if HAS_PYZBAR:
                try:
                    res = zbar_decode(scaled)
                    if res and res[0].data:
                        val = res[0].data.decode('utf-8', errors='ignore').strip()
                        if val: return val
                except Exception:
                    pass

            # Strategy B: Grayscale
            gray = cv2.cvtColor(scaled, cv2.COLOR_BGR2GRAY)
            if HAS_PYZBAR:
                try:
                    res = zbar_decode(gray)
                    if res and res[0].data:
                        val = res[0].data.decode('utf-8', errors='ignore').strip()
                        if val: return val
                except Exception:
                    pass

            # Strategy C: CLAHE Local Contrast
            clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)
            if HAS_PYZBAR:
                try:
                    res = zbar_decode(enhanced)
                    if res and res[0].data:
                        val = res[0].data.decode('utf-8', errors='ignore').strip()
                        if val: return val
                except Exception:
                    pass

            # Strategy D: Otsu Adaptive Binarization
            _, thresh = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
            if HAS_PYZBAR:
                try:
                    res = zbar_decode(thresh)
                    if res and res[0].data:
                        val = res[0].data.decode('utf-8', errors='ignore').strip()
                        if val: return val
                except Exception:
                    pass

            # Strategy E: OpenCV QR Detector fallback
            try:
                data, _, _ = cv_detector.detectAndDecode(scaled)
                if data and str(data).strip():
                    return str(data).strip()

                data, _, _ = cv_detector.detectAndDecode(gray)
                if data and str(data).strip():
                    return str(data).strip()
            except Exception:
                pass

    return None
