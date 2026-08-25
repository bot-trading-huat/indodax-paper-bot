import time
import urllib.request
import urllib.parse
import hmac
import hashlib
import json

# Masukkan API Key dan Secret Key Anda yang baru di sini:
API_KEY = "FHKI0WWQ-CREFEVQM-4NYKVNHQ-1HAGNSL4-EL9NWIEK"
SECRET_KEY = "MASUKKAN_SECRET_KEY_ANDA_DI_SINI"

def cek_api_mentah():
    url = "https://indodax.com/tapi"
    nonce = str(int(time.time() * 1000))
    params = {"method": "getInfo", "nonce": nonce}
    
    post_data = urllib.parse.urlencode(params).encode("utf-8")
    sign = hmac.new(SECRET_KEY.encode('utf-8'), post_data, hashlib.sha512).hexdigest()
    
    headers = {
        "Key": API_KEY,
        "Sign": sign,
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0"
    }
    
    try:
        req = urllib.request.Request(url, data=post_data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw_data = resp.read().decode("utf-8")
            parsed = json.loads(raw_data)
            print("\n=== HASIL MENTAH DARI INDODAX ===")
            print(json.dumps(parsed, indent=4))
            print("=================================\n")
    except Exception as e:
        print("Error koneksi:", e)

if __name__ == "__main__":
    cek_api_mentah()
