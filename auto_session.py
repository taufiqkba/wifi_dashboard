import os
import time

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# --- KONFIGURASI AKUN ---
ACCOUNTS = [
    {"name": "Kecamatan Berdaya", "user": "diskominfoprov.jateng", "pass": "12345678"},
    {
        "name": "Pelayanan Publik",
        "user": "tik_kominfo_jateng",
        "pass": "jateng#kominfo",
    },
    {"name": "POLDA Jateng 1", "user": "polda_jateng11", "pass": "jateng112"},
]

LOGIN_URL = "https://venue.wifi.id/"

# List global untuk menyimpan browser agar tidak tertutup otomatis (Garbage Collector)
ACTIVE_DRIVERS = []


def open_browser_and_login(account):
    print(f"\n🚀 Memproses: {account['name']}...")

    options = webdriver.ChromeOptions()
    options.binary_location = (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    )

    # Matikan notifikasi "Chrome is being controlled by automated software" (Opsional)
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver_path = os.path.join(os.getcwd(), "chromedriver")
    service = Service(executable_path=driver_path)

    try:
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_window_size(1200, 800)
        driver.get(LOGIN_URL)

        # Simpan driver ke list global agar tidak mati saat fungsi selesai
        ACTIVE_DRIVERS.append(driver)

        # 1. Isi Form
        try:
            wait = WebDriverWait(driver, 10)
            wait.until(EC.presence_of_element_located((By.ID, "uname"))).send_keys(
                account["user"]
            )
            driver.find_element(By.ID, "passw").send_keys(account["pass"])
            driver.find_element(By.ID, "captcha-input").click()
        except:
            print("   ⚠️  Form tidak terdeteksi sempurna (isi manual saja).")

        print("   ⏳ MENUNGGU LOGIN... (Silakan isi Captcha)")

        # 2. Tunggu sampai URL 'vdash' (Dashboard)
        while True:
            try:
                if "vdash" in driver.current_url:
                    print("   ✅ Sukses masuk Dashboard!")
                    break
                time.sleep(1)
            except:
                print("   ❌ Browser ditutup manual.")
                return None

        # 3. Ambil Session ID
        time.sleep(2)
        phpsessid = None
        for cookie in driver.get_cookies():
            if "PHPSESSID" in cookie["name"]:
                phpsessid = cookie["value"]
                break

        if phpsessid:
            # PENTING: Jangan Quit! Cukup Minimize biar gak menuhin layar.
            driver.minimize_window()
            print(f"   🎉 ID AMAN: {phpsessid}")
            print("   🔽 Browser diminimize (JANGAN DITUTUP MANUAL).")
            return phpsessid
        else:
            print("   ⚠️ Gagal ambil cookie.")
            return None

    except Exception as e:
        print(f"   ❌ Error: {e}")
        return None


# --- MAIN EXECUTION ---
if __name__ == "__main__":
    print("=" * 50)
    print(" 🕵️  WIFI.ID SESSION KEEPER (ANTI-CLOSE)")
    print("=" * 50)
    print(" PERINGATAN: Jangan tutup browser Chrome yang terbuka.")
    print(" Biarkan script ini me-minimize window-nya.")
    print("=" * 50)

    results = {}

    for acc in ACCOUNTS:
        sess = open_browser_and_login(acc)
        if sess:
            results[acc["name"]] = sess
        else:
            results[acc["name"]] = "GAGAL"

    print("\n" + "=" * 50)
    print(" 🎉 HASIL AKHIR (COPY KE DASHBOARD)")
    print("=" * 50)

    for name, sess in results.items():
        print(f"📂 {name.ljust(20)} : {sess}")

    print("=" * 50)
    print("\n⚠️  PENTING: ")
    print("   Browser Chrome sedang berjalan di background (Minimized).")
    print("   Session akan tetap AKTIF selama Anda tidak menutup script ini.")
    print(
        "   Jika pekerjaan dashboard sudah selesai, tekan ENTER di sini untuk menutup semua."
    )

    input("\n❌ TEKAN [ENTER] UNTUK MENUTUP SEMUA SESI & KELUAR...")

    print("👋 Menutup semua browser...")
    for driver in ACTIVE_DRIVERS:
        try:
            driver.quit()
        except:
            pass
    print("✅ Selesai.")
