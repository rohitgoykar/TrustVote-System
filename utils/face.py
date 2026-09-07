import os
import glob
import base64
import cv2
import numpy as np

# ─────────────────────────────────────────────────────────────────
# TrustVote - Fast + Accurate Face Recognition
# Uses DeepFace with "Facenet" model
# ─────────────────────────────────────────────────────────────────

USE_DEEP = False
try:
    from deepface import DeepFace
    print("[TrustVote] [Loading] Pre-loading Facenet model, please wait...")
    DeepFace.build_model("Facenet")
    USE_DEEP = True
    print("[TrustVote] [OK] Facenet model loaded — face verification will be fast!")
except ImportError:
    print("[TrustVote] [Warning] DeepFace not installed. Using fallback.")

face_cascade = None
try:
    if hasattr(cv2, 'data') and hasattr(cv2.data, 'haarcascades'):
        CASCADE_PATH = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        if hasattr(cv2, 'CascadeClassifier'):
            face_cascade = cv2.CascadeClassifier(CASCADE_PATH)
except Exception as e:
    print(f"[TrustVote] [Cascade] Info: {e}")


def decode_base64_image(b64_string):
    if ',' in b64_string:
        b64_string = b64_string.split(',')[1]
    img_bytes = base64.b64decode(b64_string)
    img_array = np.frombuffer(img_bytes, dtype=np.uint8)
    return cv2.imdecode(img_array, cv2.IMREAD_COLOR)


def extract_face_roi(img):
    if img is None:
        return None
    if face_cascade is None or not hasattr(face_cascade, 'detectMultiScale'):
        h, w = img.shape[:2]
        return img[int(h*0.05):int(h*0.95), int(w*0.05):int(w*0.95)]

    gray  = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray  = cv2.equalizeHist(gray)
    faces = face_cascade.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=6, minSize=(80, 80)
    )
    if len(faces) == 0:
        return None
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    pad = int(0.15 * min(w, h))
    x1  = max(0, x - pad)
    y1  = max(0, y - pad)
    x2  = min(img.shape[1], x + w + pad)
    y2  = min(img.shape[0], y + h + pad)
    return img[y1:y2, x1:x2]
    x2  = min(img.shape[1], x + w + pad)
    y2  = min(img.shape[0], y + h + pad)
    return img[y1:y2, x1:x2]


def _deepface_compare(img1_bgr, img2_bgr):
    try:
        result = DeepFace.verify(
            img1_path=img1_bgr,
            img2_path=img2_bgr,
            model_name="Facenet",
            detector_backend="opencv",
            enforce_detection=False
        )
        is_match   = result["verified"]
        distance   = result["distance"]
        confidence = round(max(0.0, (1.0 - distance)) * 100, 1)
        return is_match, confidence
    except Exception as e:
        print(f"[DeepFace error] {e}")
        return False, 0.0


def _histogram_compare(img1, img2, threshold=0.72):
    size = (128, 128)
    f1   = cv2.resize(img1, size)
    f2   = cv2.resize(img2, size)
    scores = []
    f1_hsv = cv2.cvtColor(f1, cv2.COLOR_BGR2HSV)
    f2_hsv = cv2.cvtColor(f2, cv2.COLOR_BGR2HSV)
    for ch in [0, 1]:
        h1 = cv2.calcHist([f1_hsv], [ch], None, [64], [0, 256])
        h2 = cv2.calcHist([f2_hsv], [ch], None, [64], [0, 256])
        cv2.normalize(h1, h1); cv2.normalize(h2, h2)
        scores.append(cv2.compareHist(h1, h2, cv2.HISTCMP_CORREL))
    g1  = cv2.cvtColor(f1, cv2.COLOR_BGR2GRAY)
    g2  = cv2.cvtColor(f2, cv2.COLOR_BGR2GRAY)
    hg1 = cv2.calcHist([g1], [0], None, [64], [0, 256])
    hg2 = cv2.calcHist([g2], [0], None, [64], [0, 256])
    cv2.normalize(hg1, hg1); cv2.normalize(hg2, hg2)
    scores.append(cv2.compareHist(hg1, hg2, cv2.HISTCMP_CORREL))
    g1_eq = cv2.equalizeHist(g1)
    g2_eq = cv2.equalizeHist(g2)
    diff  = cv2.absdiff(g1_eq, g2_eq)
    mse   = np.mean(diff.astype(np.float32) ** 2)
    scores.append(1.0 - min(mse / 5000.0, 1.0))
    avg = float(np.mean(scores))
    return avg >= threshold, round(avg * 100, 1)


def compare_faces(img1, img2):
    """Used by verify_routes.py for booth face verification."""
    if USE_DEEP:
        return _deepface_compare(img1, img2)
    else:
        return _histogram_compare(img1, img2)


def check_duplicate_face(new_img, storage_dir):
    """
    Called during registration to block duplicate face enrollments.
    Compares new_img (numpy BGR array) against every stored photo.
    Returns (True, existing_vid) if duplicate found, else (False, None).
    """
    stored_photos = glob.glob(os.path.join(storage_dir, "*.jpg"))
    if not stored_photos:
        return False, None

    for stored_path in stored_photos:
        try:
            stored_img = cv2.imread(stored_path)
            if stored_img is None:
                continue

            if USE_DEEP:
                result = DeepFace.verify(
                    img1_path=new_img,
                    img2_path=stored_img,
                    model_name="Facenet",
                    detector_backend="opencv",
                    enforce_detection=False
                )
                # Stricter threshold for registration (0.35 vs 0.50 for login)
                is_match = result["distance"] < 0.35
            else:
                is_match, _ = _histogram_compare(new_img, stored_img, threshold=0.85)

            if is_match:
                existing_vid = os.path.splitext(os.path.basename(stored_path))[0]
                return True, existing_vid

        except Exception as e:
            print(f"[FaceDupCheck] Error comparing {stored_path}: {e}")
            continue

    return False, None