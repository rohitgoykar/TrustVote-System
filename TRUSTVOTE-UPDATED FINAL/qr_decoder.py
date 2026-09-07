import os
import cv2
import numpy as np

def decode_qr_from_image(image_bytes):
    """
    Robust multi-strategy QR code extractor:
    1. Direct OpenCV QR Detector on original image
    2. Grayscale + CLAHE + Adaptive thresholding
    3. Multi-quadrant intelligent cropping (Right half, Top-Right, Center-Right)
    4. Multi-scale detection (Resized & Sharpened)
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return None

    detector = cv2.QRCodeDetector()

    # Strategy 1: Direct detection on full image
    data, bbox, _ = detector.detectAndDecode(img)
    if data:
        return data

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    data, _, _ = detector.detectAndDecode(gray)
    if data:
        return data

    # Strategy 2: Multi-quadrant crop for dual-sided cards
    h, w = img.shape[:2]
    
    # Check right half where back of card is located
    right_half = img[:, int(w * 0.45):]
    data, _, _ = detector.detectAndDecode(right_half)
    if data:
        return data

    # Crop the exact QR box region (y: 5% to 80% of right half)
    qr_pouch = right_half[int(h * 0.05):int(h * 0.85), :]
    data, _, _ = detector.detectAndDecode(qr_pouch)
    if data:
        return data

    # Strategy 3: Contrast & Binarization on pouch
    pouch_gray = cv2.cvtColor(qr_pouch, cv2.COLOR_BGR2GRAY)
    data, _, _ = detector.detectAndDecode(pouch_gray)
    if data:
        return data

    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8,8))
    enhanced = clahe.apply(pouch_gray)
    data, _, _ = detector.detectAndDecode(enhanced)
    if data:
        return data

    _, thresh = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    data, _, _ = detector.detectAndDecode(thresh)
    if data:
        return data

    # Strategy 4: Scaling up / down
    for scale in [1.5, 0.75, 2.0]:
        scaled = cv2.resize(pouch_gray, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        data, _, _ = detector.detectAndDecode(scaled)
        if data:
            return data

    return None

if __name__ == "__main__":
    print("Multi-strategy QR Decoder module ready.")
