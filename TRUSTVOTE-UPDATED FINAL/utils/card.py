import os
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from config import ID_CARDS_DIR

def english_to_devanagari(text):
    text = text.lower().strip()
    text = text.split(" s/o ")[0]
    
    mapping = [
        ("ksh", "क्ष"), ("sh", "श"), ("ch", "च"), ("kh", "ख"), ("gh", "घ"), 
        ("th", "थ"), ("dh", "ध"), ("bh", "भ"), ("ph", "फ"), ("jh", "झ"),
        ("k", "क"), ("g", "ग"), ("j", "ज"), ("t", "त"), ("d", "द"), 
        ("n", "न"), ("p", "प"), ("b", "ब"), ("m", "म"), ("y", "य"), 
        ("r", "र"), ("l", "ल"), ("v", "व"), ("w", "व"), ("h", "ह"), ("s", "स"),
        ("ai", "ऐ"), ("au", "औ"), ("aa", "आ"), ("a", "अ"), ("ee", "ई"), 
        ("i", "इ"), ("oo", "ऊ"), ("u", "उ"), ("e", "ए"), ("o", "ओ"),
    ]
    
    vowel_marks = {
        "aa": "ा", "a": "", "ee": "ी", "i": "ि", "oo": "ू", "u": "ु", 
        "e": "े", "ai": "ै", "o": "ो", "au": "ौ"
    }
    
    words = text.split()
    dev_words = []
    for word in words:
        known = {
            "rohit": "रोहित", "nanasaheb": "नानासाहेब", "goykar": "गोयकर",
            "roshni": "रोशनी", "amit": "अमित", "rahul": "राहुल", "sanjay": "संजय", "anil": "अनिल",
            "sunita": "सुनीता", "priya": "प्रिया", "pooja": "पूजा", "sneha": "स्नेहा",
            "rajesh": "राजेश", "ram": "राम", "sham": "शाम", "shyam": "श्याम",
            "santosh": "संतोष", "kulkarni": "कुलकर्णी", "deshmukh": "देशमुख", "patil": "पाटील",
            "shinde": "शिंदे", "pawar": "पवार", "gaikwad": "गायकवाड", "jadhav": "जाधव"
        }
        if word in known:
            dev_words.append(known[word])
            continue
        
        res = ""
        i = 0
        n = len(word)
        while i < n:
            matched_consonant = False
            for eng, dev in mapping[:16]:
                l = len(eng)
                if word[i:i+l] == eng:
                    res += dev
                    i += l
                    matched_consonant = True
                    break
            
            if matched_consonant:
                matched_vowel = False
                for eng_v, mark in vowel_marks.items():
                    l = len(eng_v)
                    if i < n and word[i:i+l] == eng_v:
                        res += mark
                        i += l
                        matched_vowel = True
                        break
                if not matched_vowel and i < n and word[i] == 'a':
                    i += 1
                continue
            
            matched_any = False
            for eng, dev in mapping[16:]:
                l = len(eng)
                if word[i:i+l] == eng:
                    res += dev
                    i += l
                    matched_any = True
                    break
            
            if not matched_any:
                res += word[i]
                i += 1
        dev_words.append(res)
    return " ".join(dev_words)

def draw_card_background(draw, cx, cy, width, height):
    # Tricolor subtle gradient
    for y in range(height):
        factor = y / height
        if factor < 0.35:
            # Light Saffron
            blend = factor / 0.35
            r = int(255 * (1 - blend) + 255 * blend)
            g = int(245 * (1 - blend) + 255 * blend)
            b = int(235 * (1 - blend) + 255 * blend)
        elif factor < 0.65:
            # Pure White
            r, g, b = 255, 255, 255
        else:
            # Light Green
            blend = (factor - 0.65) / 0.35
            r = int(255 * (1 - blend) + 238 * blend)
            g = int(255 * (1 - blend) + 250 * blend)
            b = int(255 * (1 - blend) + 238 * blend)
            
        draw.line([(cx, cy + y), (cx + width, cy + y)], fill=(r, g, b))

    # Security guilloche rings
    for radius in range(50, 260, 30):
        draw.ellipse([cx + width//2 - radius, cy + height//2 - radius, 
                      cx + width//2 + radius, cy + height//2 + radius], 
                     outline=(245, 245, 245), width=1)

def draw_centered_text(draw, card_x, card_width, y, text, font, fill):
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    x = card_x + (card_width - w) // 2
    draw.text((x, y), text, font=font, fill=fill)

def create_voter_card(vid, name, dob, gender, photo_path, district="", constituency=""):
    # Dual-sided canvas (Front on Left, Back on Right)
    canvas = Image.new('RGB', (800, 560), color=(241, 245, 249))
    draw = ImageDraw.Draw(canvas)

    card_w, card_h = 370, 520
    fx, fy = 20, 20     # Front Card start
    bx, by = 410, 20    # Back Card start

    # Load Fonts
    try:
        font_header = ImageFont.truetype("arialbd.ttf", 13)
        font_epic   = ImageFont.truetype("arialbd.ttf", 15)
        font_data   = ImageFont.truetype("arial.ttf",   12)
        font_bold   = ImageFont.truetype("arialbd.ttf", 12)
        font_small  = ImageFont.truetype("arial.ttf",   10)
        font_micro  = ImageFont.truetype("arial.ttf",   9)
    except Exception:
        font_header = font_epic = font_data = font_bold = font_small = font_micro = ImageFont.load_default()

    try:
        font_marathi = ImageFont.truetype("Nirmala.ttf", 14)
        font_marathi_bold = ImageFont.truetype("NirmalaB.ttf", 13)
    except Exception:
        try:
            font_marathi = ImageFont.truetype("mangal.ttf", 14)
            font_marathi_bold = font_marathi
        except Exception:
            font_marathi = font_data
            font_marathi_bold = font_bold

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 1. FRONT SIDE OF CARD (Official SEC Maharashtra Voter ID)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    draw_card_background(draw, fx, fy, card_w, card_h)
    draw.rectangle([fx, fy, fx + card_w, fy + card_h], outline=(203, 213, 225), width=2)

    # Tricolor top stripe
    draw.rectangle([fx, fy, fx + card_w, fy + 5], fill=(255, 153, 51))
    draw.rectangle([fx, fy + 5, fx + card_w, fy + 9], fill=(255, 255, 255))
    draw.rectangle([fx, fy + 9, fx + card_w, fy + 14], fill=(19, 136, 8))

    # Header: SEC Maharashtra
    draw_centered_text(draw, fx, card_w, fy + 18, "महाराष्ट्र राज्य निवडणूक आयोग", font_marathi_bold, (15, 23, 42))
    draw_centered_text(draw, fx, card_w, fy + 36, "STATE ELECTION COMMISSION MAHARASHTRA", font_micro, (71, 85, 105))
    draw_centered_text(draw, fx, card_w, fy + 50, "ELECTION PHOTO IDENTITY CARD", font_header, (15, 23, 42))

    # Gold EPIC Box
    draw.rectangle([fx + 25, fy + 70, fx + card_w - 25, fy + 98], fill=(254, 240, 138), outline=(234, 179, 8), width=2)
    draw_centered_text(draw, fx, card_w, fy + 75, f"EPIC NO : {vid}", font_epic, (113, 63, 18))

    # Photo (Centered)
    photo_w, photo_h = 135, 160
    px = fx + 25
    py = fy + 115
    try:
        v_img = Image.open(photo_path).resize((photo_w, photo_h))
        canvas.paste(v_img, (px, py))
        draw.rectangle([px - 1, py - 1, px + photo_w + 1, py + photo_h + 1], outline=(30, 41, 59), width=2)
    except Exception:
        draw.rectangle([px, py, px + photo_w, py + photo_h], outline=(148, 163, 184), width=1)
        draw.text((px + 40, py + 70), "PHOTO", font=font_small, fill=(100, 116, 139))

    # Voter Details next to photo
    dx = px + photo_w + 15
    dy = py + 5

    # Marathi Name
    local_name = english_to_devanagari(name)
    draw.text((dx, dy), "नाव / Name:", font=font_micro, fill=(100, 116, 139))
    draw.text((dx, dy + 14), local_name, font=font_marathi, fill=(15, 23, 42))
    draw.text((dx, dy + 32), name.split(" S/O ")[0], font=font_bold, fill=(15, 23, 42))

    # Gender & DOB
    draw.text((dx, dy + 62), "लिंग / Gender:", font=font_micro, fill=(100, 116, 139))
    draw.text((dx, dy + 76), gender.upper(), font=font_bold, fill=(15, 23, 42))

    try:
        dob_dt = datetime.strptime(dob, '%Y-%m-%d')
        dob_formatted = dob_dt.strftime('%d-%b-%Y')
    except Exception:
        dob_formatted = dob

    draw.text((dx, dy + 100), "जन्म तारीख / DOB:", font=font_micro, fill=(100, 116, 139))
    draw.text((dx, dy + 114), dob_formatted, font=font_bold, fill=(15, 23, 42))

    # District & Constituency Details Box
    box_y = fy + 290
    draw.rectangle([fx + 20, box_y, fx + card_w - 20, box_y + 160], fill=(255, 255, 255), outline=(226, 232, 240), width=1)
    
    clean_dist = district.split('(')[0].strip() if district else "Maharashtra"
    clean_const = constituency if constituency else "General"
    
    draw.text((fx + 30, box_y + 10), "जिल्हा / District:", font=font_micro, fill=(100, 116, 139))
    draw.text((fx + 30, box_y + 24), clean_dist, font=font_bold, fill=(15, 23, 42))

    draw.text((fx + 30, box_y + 50), "मतदारसंघ / Constituency:", font=font_micro, fill=(100, 116, 139))
    draw.text((fx + 30, box_y + 64), clean_const[:32], font=font_bold, fill=(15, 23, 42))

    draw.text((fx + 30, box_y + 92), "स्थानिक स्वराज्य संस्था / Local Tier:", font=font_micro, fill=(100, 116, 139))
    draw.text((fx + 30, box_y + 106), "SEC Maharashtra Electoral Roll", font=font_bold, fill=(22, 163, 74))
    
    draw.text((fx + 30, box_y + 130), "Security Status: BIOMETRIC ENROLLED", font=font_micro, fill=(5, 150, 105))

    # Bottom Footer
    draw.rectangle([fx, fy + card_h - 26, fx + card_w, fy + card_h], fill=(15, 23, 42))
    draw_centered_text(draw, fx, card_w, fy + card_h - 20, "महाराष्ट्र शासन • STATE ELECTION COMMISSION", font_micro, (255, 255, 255))


    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 2. BACK SIDE OF CARD (Encrypted QR Code & Verification Pouch)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    draw_card_background(draw, bx, by, card_w, card_h)
    draw.rectangle([bx, by, bx + card_w, by + card_h], outline=(203, 213, 225), width=2)

    # Tricolor top stripe
    draw.rectangle([bx, by, bx + card_w, by + 5], fill=(255, 153, 51))
    draw.rectangle([bx, by + 5, bx + card_w, by + 9], fill=(255, 255, 255))
    draw.rectangle([bx, by + 9, bx + card_w, by + 14], fill=(19, 136, 8))

    # Back Header
    draw_centered_text(draw, bx, card_w, by + 20, "डिजिटल बायोमेट्रिक ओळख पास", font_marathi_bold, (15, 23, 42))
    draw_centered_text(draw, bx, card_w, by + 38, "DIGITAL BIOMETRIC VOTING PASS", font_micro, (71, 85, 105))

    # Security QR Container Pouch
    qw, qh = 240, 240
    qx = bx + (card_w - qw) // 2
    qy = by + 65

    draw.rectangle([qx - 10, qy - 10, qx + qw + 10, qy + qh + 10], fill=(255, 255, 255), outline=(148, 163, 184), width=2)

    try:
        qr_path = os.path.join(ID_CARDS_DIR, vid + "_qr.png")
        qr_img  = Image.open(qr_path).resize((qw, qh))
        canvas.paste(qr_img, (qx, qy))
    except Exception:
        draw.rectangle([qx, qy, qx + qw, qy + qh], outline=(200, 200, 200), width=1)
        draw.text((qx + 50, qy + 110), "[QR CODE MISSING]", font=font_small, fill=(150, 150, 150))

    # Verification Instructions below QR
    draw_centered_text(draw, bx, card_w, by + 335, "मतदान केंद्रावर बायोमेट्रिक पडताळणीसाठी हा QR स्कॅन करा", font_marathi, (15, 23, 42))
    draw_centered_text(draw, bx, card_w, by + 355, "Scan this QR code at Polling Booth for Face Authentication", font_micro, (100, 116, 139))

    # Important Guidelines Box
    guideline_y = by + 380
    draw.rectangle([bx + 20, guideline_y, bx + card_w - 20, guideline_y + 90], fill=(248, 250, 252), outline=(226, 232, 240), width=1)
    
    draw.text((bx + 30, guideline_y + 8), "• This card is valid for Maharashtra Local Body Elections.", font=font_micro, fill=(51, 65, 85))
    draw.text((bx + 30, guideline_y + 24), "• Voter identity is verified via Facial Biometrics & Encrypted QR.", font=font_micro, fill=(51, 65, 85))
    draw.text((bx + 30, guideline_y + 40), "• Duplicate voting across wards/booths is strictly prohibited.", font=font_micro, fill=(220, 38, 38))
    draw.text((bx + 30, guideline_y + 60), f"SEC Auth Hash: SEC-MH-{vid}-{datetime.now().strftime('%Y%m%d')}", font=font_micro, fill=(100, 116, 139))

    # Back Footer
    draw.rectangle([bx, by + card_h - 26, bx + card_w, by + card_h], fill=(15, 23, 42))
    draw_centered_text(draw, bx, card_w, by + card_h - 20, "SEC MAHARASHTRA • CONFIDENTIAL VOTER DATA", font_micro, (255, 255, 255))

    # Save Dual-Sided Card
    card_file = os.path.join(ID_CARDS_DIR, vid + "_final_card.png")
    canvas.save(card_file)
    return card_file

def create_voting_pass(vid, name, district="", constituency=""):
    """
    Creates an official stand-alone SEC Maharashtra Voting Pass with the high-resolution QR code.
    """
    canvas = Image.new('RGB', (600, 760), color=(255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    # Tricolor border
    draw.rectangle([0, 0, 600, 10], fill=(255, 153, 51))
    draw.rectangle([0, 10, 600, 16], fill=(255, 255, 255))
    draw.rectangle([0, 16, 600, 24], fill=(19, 136, 8))
    draw.rectangle([10, 24, 590, 750], outline=(203, 213, 225), width=2)

    try:
        font_title = ImageFont.truetype("arialbd.ttf", 20)
        font_sub = ImageFont.truetype("arialbd.ttf", 13)
        font_bold = ImageFont.truetype("arialbd.ttf", 14)
        font_data = ImageFont.truetype("arial.ttf", 13)
        font_small = ImageFont.truetype("arial.ttf", 11)
        font_marathi = ImageFont.truetype("NirmalaB.ttf", 18)
    except Exception:
        font_title = font_sub = font_bold = font_data = font_small = font_marathi = ImageFont.load_default()

    # Header
    draw_centered_text(draw, 0, 600, 45, "महाराष्ट्र राज्य निवडणूक आयोग", font_marathi, (15, 23, 42))
    draw_centered_text(draw, 0, 600, 75, "STATE ELECTION COMMISSION MAHARASHTRA", font_sub, (71, 85, 105))
    draw_centered_text(draw, 0, 600, 95, "OFFICIAL VOTING PASS & SCANNER QR CODE", font_title, (22, 163, 74))

    # Divider
    draw.line([(40, 130), (560, 130)], fill=(226, 232, 240), width=2)

    # Voter Info Box
    draw.rectangle([40, 145, 560, 245], fill=(248, 250, 252), outline=(226, 232, 240), width=2)
    
    draw.text((60, 160), "EPIC (Voter ID):", font=font_bold, fill=(71, 85, 105))
    draw.text((200, 160), vid, font=font_bold, fill=(15, 23, 42))

    draw.text((60, 185), "Voter Name:", font=font_bold, fill=(71, 85, 105))
    draw.text((200, 185), name, font=font_bold, fill=(15, 23, 42))

    clean_dist = district.split('(')[0].strip() if district else "Maharashtra"
    draw.text((60, 210), "District / मतदारसंघ:", font=font_bold, fill=(71, 85, 105))
    draw.text((200, 210), f"{clean_dist} | {constituency or 'General'}", font=font_data, fill=(15, 23, 42))

    # Large QR Code with white quiet zone
    qw, qh = 300, 300
    qx = (600 - qw) // 2
    qy = 275

    draw.rectangle([qx - 20, qy - 20, qx + qw + 20, qy + qh + 20], fill=(255, 255, 255), outline=(203, 213, 225), width=2)

    try:
        qr_path = os.path.join(ID_CARDS_DIR, vid + "_qr.png")
        qr_img  = Image.open(qr_path).resize((qw, qh))
        canvas.paste(qr_img, (qx, qy))
    except Exception:
        draw.text((qx + 80, qy + 150), "[QR CODE MISSING]", font=font_bold, fill=(239, 68, 68))

    # Instructions
    draw_centered_text(draw, 0, 600, 625, "मतदान केंद्रावर हा QR कोड दाखवून चेहरा पडताळणी पूर्ण करा.", font_sub, (15, 23, 42))
    draw_centered_text(draw, 0, 600, 648, "Hold this pass in front of Polling Booth Camera for Instant Verification.", font_small, (100, 116, 139))

    # Footer
    draw.rectangle([0, 720, 600, 760], fill=(15, 23, 42))
    draw_centered_text(draw, 0, 600, 732, "SEC MAHARASHTRA • CONFIDENTIAL ELECTORAL PASS", font_small, (255, 255, 255))

    pass_file = os.path.join(ID_CARDS_DIR, vid + "_qr_pass.png")
    canvas.save(pass_file)
    return pass_file
