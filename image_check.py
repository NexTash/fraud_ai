from PIL import Image

def check_app(path):
    img = Image.open(path).convert("L")

    samples = {
        "WhatsApp": "static/whatsapp.png",
        "Facebook": "static/facebook.png",
        "Instagram": "static/instagram.png"
    }

    for name, sample_path in samples.items():
        try:
            sample = Image.open(sample_path).convert("L")

            if img.size == sample.size:
                return f"✅ REAL APP ({name})"
        except:
            continue

    return "🚨 FAKE / UNKNOWN APP"