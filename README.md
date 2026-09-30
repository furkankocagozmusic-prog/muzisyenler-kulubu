
# Müzisyenler Kulübü — Gerçek Zamanlı Yerel Sürüm

Bu sürüm bilgisayarında çalışır. Render/Supabase gerekmez.

## 1) Python
Python 3.10+ kurulu olsun.

## 2) Kurulum
Terminali bu klasörde aç:
    pip install -r requirements.txt

## 3) Çalıştır
    python app.py

Sonra tarayıcıdan:
    http://127.0.0.1:5000

## Özellikler
- Gerçek kayıt/giriş
- SQLite veritabanı
- Gerçek zamanlı oda sohbeti (Socket.IO)
- Çevrimiçi müzisyen listesi
- Profil düzenleme
- Müzisyen arama
- Özel mesaj altyapısı
- Mesajların yerel veritabanına kaydı
- Mobil uyumlu koyu mor arayüz

Not: Bu sürüm yerel geliştirme içindir. İnternete açmadan önce güvenlik, HTTPS, production server, rate limit ve kalıcı kullanıcı oturumu gibi konular ayrıca ele alınmalıdır.


## Admin
İlk kayıt olan kullanıcı otomatik olarak **admin** olur. Admin panelinden kullanıcı rolleri ve ilanlar yönetilebilir.
