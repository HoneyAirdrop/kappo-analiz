import streamlit as st
import yfinance as yf
import pandas as pd
import google.generativeai as genai
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import re
import difflib
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone, timedelta

# --- 1. AYARLAR VE API ---
GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]

try:
    genai.configure(api_key=GOOGLE_API_KEY)
except Exception as e:
    st.error(f"API Yapılandırma Hatası: {e}")

st.set_page_config(page_title="Borsa Analiz (Kappo)", layout="wide", page_icon="📈")

# --- SESSION STATE (DURUM YÖNETİMİ) ---
if "sayfa" not in st.session_state:
    st.session_state.sayfa = 1

if "ana_hisse" not in st.session_state:
    st.session_state.ana_hisse = "THYAO - Türk Hava Yolları A.O."

def arama_temizle_ve_sec():
    if st.session_state.arama_kutusu:
        st.session_state.ana_hisse = st.session_state.arama_kutusu
        st.session_state.arama_kutusu = None  

def sektor_secimi_guncelle():
    st.session_state.ana_hisse = st.session_state.sektor_kutusu

# --- YARDIMCI FONKSİYONLAR VE SAAT DİLİMİ (TIMEZONE) ---

# Sabit Türkiye Zaman Dilimi (UTC+3)
TR_TZ = timezone(timedelta(hours=3))

def haber_uygun_mu(baslik, ozet):
    istenmeyen_kelimeler = ["teknik analiz", "hedef fiyat", "grafik", "destek direnç", "destek ve direnç", "alım satım", "al-sat"]
    metin = (baslik + " " + ozet).lower()
    
    for kelime in istenmeyen_kelimeler:
        if kelime in metin:
            return False 
    return True

def html_temizle(raw_html, baslik=""):
    if not raw_html:
        return ""
    
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html).strip()
    cleantext = re.sub(r'^[\-\|\:\.]+', '', cleantext).strip()
    
    if baslik:
        def _harf_temizle(s):
            return re.sub(r'\W+', '', s.lower()) 
            
        cmp_desc = _harf_temizle(cleantext)
        cmp_baslik = _harf_temizle(baslik)
        
        if cmp_baslik in cmp_desc or cmp_desc in cmp_baslik:
            return ""
        
        similarity = difflib.SequenceMatcher(None, cmp_desc, cmp_baslik).ratio()
        if similarity > 0.6:
            return ""
            
    return cleantext

def tarih_formatla_ve_sirala(tarih_str):
    try:
        # RSS'den gelen tarihi okur (Genelde UTC/GMT olur)
        dt = parsedate_to_datetime(tarih_str)
        
        # Eğer saatte bir dilim belirtilmemişse, onu zorla UTC kabul ederiz
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
            
        # Saati GARANTİLİ olarak Türkiye Saatine (UTC+3) çeviririz
        dt = dt.astimezone(TR_TZ)
            
        gunler = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
        aylar = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
        
        turkce_tarih = f"{gunler[dt.weekday()]}, {dt.day} {aylar[dt.month]} {dt.year} {dt.strftime('%H:%M:%S')}"
        return turkce_tarih, dt
    except:
        # Tarih bozuk gelirse, haberin en dibe düşmesi için onu 2000 yılına fırlatıyoruz
        eski_tarih = datetime(2000, 1, 1, tzinfo=TR_TZ)
        return tarih_str, eski_tarih

# --- HABER ÇEKME MOTORLARI ---
@st.cache_data(ttl=300) 
def rss_haber_cek(arama_kelimesi, limit=15):
    try:
        query = urllib.parse.quote(arama_kelimesi)
        url = f"https://news.google.com/rss/search?q={query}&hl=tr&gl=TR&ceid=TR:tr"

        req = urllib.request.Request(
            url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )

        with urllib.request.urlopen(req) as response:
            xml_data = response.read()

        root = ET.fromstring(xml_data)
        haberler = []
        
        for item in root.findall('./channel/item'):
            title = item.find('title').text if item.find('title') is not None else ""
            link = item.find('link').text if item.find('link') is not None else "#"
            pub_date = item.find('pubDate').text if item.find('pubDate') is not None else ""
            description = item.find('description').text if item.find('description') is not None else ""
            
            turkce_tarih, dt_obj = tarih_formatla_ve_sirala(pub_date)
            temiz_ozet = html_temizle(description, baslik=title)

            if haber_uygun_mu(title, temiz_ozet):
                haberler.append({
                    "baslik": title,
                    "ozet": temiz_ozet[:250] + "..." if len(temiz_ozet) > 250 else temiz_ozet,
                    "link": link,
                    "tarih": turkce_tarih,
                    "dt_obj": dt_obj
                })
            
        haberler.sort(key=lambda x: x["dt_obj"], reverse=True)
        return haberler[:limit] if haberler else []
    except Exception as e:
        return []

@st.cache_data(ttl=300)
def bloomberg_ht_cek(limit=30): 
    try:
        url = "https://www.bloomberght.com/rss"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        
        with urllib.request.urlopen(req) as response:
            xml_data = response.read()

        root = ET.fromstring(xml_data)
        haberler = []
        
        for item in root.findall('./channel/item'):
            title = item.find('title').text
            link = item.find('link').text
            pub_date = item.find('pubDate').text
            description = item.find('description').text
            
            turkce_tarih, dt_obj = tarih_formatla_ve_sirala(pub_date)
            temiz_ozet = html_temizle(description, baslik=title)

            if haber_uygun_mu(title, temiz_ozet):
                haberler.append({
                    "baslik": title,
                    "ozet": temiz_ozet[:200] + "..." if len(temiz_ozet) > 200 else temiz_ozet,
                    "link": link,
                    "tarih": turkce_tarih,
                    "dt_obj": dt_obj
                })
            
        haberler.sort(key=lambda x: x["dt_obj"], reverse=True)
        return haberler[:limit]
    except:
        return []

# --- ÖZEL HTML/CSS HABER KARTI TASARIMI (HİSSE, SEKTÖR VE ESKİ BLOOMBERG İÇİN) ---
def haber_karti_olustur(haber, renk_temasi="mavi", sira_no=None, expander_icinde=False):
    if not expander_icinde:
        if renk_temasi == "mavi":
            bg_color, border_color = "#0B192C", "#3B82F6"
        elif renk_temasi == "sari":
            bg_color, border_color = "#2E1B05", "#F59E0B"
        else: # yesil
            bg_color, border_color = "#062E1A", "#10B981"
    else:
        bg_color = "#111827"  
        if renk_temasi == "mavi":
            border_color = "#3B82F6" 
        elif renk_temasi == "sari":
            border_color = "#D97706"
        else:
            border_color = "#059669"

    if sira_no:
        ikon_kismi = f"<span style='background-color:{border_color}; color:#111; padding: 2px 7px; border-radius: 4px; font-weight: 900; margin-right: 6px;'>{sira_no}</span>"
    else:
        ikon_kismi = "🗓️ "

    text_color = "#F9FAFB" if not expander_icinde else "#D1D5DB"
    ozet_html = f"<p style='color:#9CA3AF; font-size: 14px; margin: 8px 0;'><em>{haber['ozet']}</em></p>" if len(haber['ozet']) > 5 else ""

    html_kodu = f"""<div style="background-color: {bg_color}; border-left: 4px solid {border_color}; padding: 15px; border-radius: 5px; margin-bottom: 15px;">
<div style="font-size: 13px; color: #6B7280; margin-bottom: 8px;">{ikon_kismi} <b>{haber['tarih']}</b></div>
<div style="font-size: 16px; font-weight: bold; color: {text_color};">{haber['baslik']}</div>
{ozet_html}
<a href="{haber['link']}" target="_blank" style="color: {border_color}; text-decoration: none; font-size: 14px; font-weight: bold; display: inline-block; margin-top: 8px;">Habere Git ↗</a>
</div>"""
    st.markdown(html_kodu, unsafe_allow_html=True)


# --- YENİ BLOOMBERG HT SON DAKİKA KARTI (KIRMIZI-SİYAH MİNİMAL TASARIM) ---
def bloomberg_karti_olustur(haber, sira_no, expander_icinde=False):
    saat = haber['dt_obj'].strftime('%H:%M')
    
    gunler = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    aylar = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
    tarih_kisa = f"{haber['dt_obj'].day} {aylar[haber['dt_obj'].month]} {haber['dt_obj'].year}, {gunler[haber['dt_obj'].weekday()]}"
    
    bg_color = "#000000" if not expander_icinde else "#111827"
    text_color = "#F9FAFB" if not expander_icinde else "#D1D5DB"

    html_kodu = f"""
    <div style="background-color: {bg_color}; border-bottom: 1px solid #374151; padding: 12px 5px; margin-bottom: 8px;">
        <div style="display: flex; justify-content: space-between; align-items: flex-start;">
            <div style="display: flex; align-items: center;">
                <div style="border-left: 4px solid #DC2626; padding-left: 8px;">
                    <div style="background-color: #FECACA; color: #991B1B; font-size: 16px; font-weight: 900; padding: 3px 8px; border-radius: 3px; display: inline-block;">
                        {saat}
                    </div>
                </div>
                <div style="margin-left: 12px; color: #6B7280; font-size: 14px; font-weight: bold;">
                    #{sira_no}
                </div>
            </div>
            <div style="color: #6B7280; font-size: 20px;">
                <a href="{haber['link']}" target="_blank" style="color: inherit; text-decoration: none;">⇱</a>
            </div>
        </div>
        <div style="color: #9CA3AF; font-size: 12px; margin-top: 8px; margin-bottom: 4px;">{tarih_kisa}</div>
        <div style="color: {text_color}; font-size: 15px; font-weight: 800; font-family: sans-serif; line-height: 1.4;">
            <a href="{haber['link']}" target="_blank" style="color: inherit; text-decoration: none;">{haber['baslik'].upper()}</a>
        </div>
    </div>
    """
    st.markdown(html_kodu, unsafe_allow_html=True)


# --- BİST 100 KATEGORİK HİSSE LİSTESİ ---
BIST_HISSELER = {
    "Bankacılık": {"AKBNK": "Akbank T.A.Ş.", "ALBRK": "Albaraka Türk Katılım Bankası A.Ş.", "GARAN": "Türkiye Garanti Bankası A.Ş.", "HALKB": "Türkiye Halk Bankası A.Ş.", "ISCTR": "Türkiye İş Bankası A.Ş. (C)", "SKBNK": "Şekerbank T.A.Ş.", "TSKB": "Türkiye Sınai Kalkınma Bankası A.Ş.", "VAKBN": "VakıfBank T.A.O.", "YKBNK": "Yapı ve Kredi Bankası A.Ş."},
    "Holding ve Yatırım": {"AGHOL": "AG Anadolu Grubu Holding A.Ş.", "ALARK": "Alarko Holding A.Ş.", "BERA": "Bera Holding A.Ş.", "BRYAT": "Borusan Yatırım ve Pazarlama A.Ş.", "DOHOL": "Doğan Şirketler Grubu Holding A.Ş.", "KCHOL": "Koç Holding A.Ş.", "SAHOL": "Sabancı Holding A.Ş.", "TKFEN": "Tekfen Holding A.Ş."},
    "Havacılık": {"PGSUS": "Pegasus Hava Taşımacılığı A.Ş.", "TAVHL": "TAV Havalimanları Holding A.Ş.", "THYAO": "Türk Hava Yolları A.O."},
    "Otomotiv ve Yan Sanayi": {"DOAS": "Doğuş Otomotiv Servis ve Ticaret A.Ş.", "EGEEN": "Ege Endüstri ve Ticaret A.Ş.", "FROTO": "Ford Otomotiv Sanayi A.Ş.", "KARSN": "Karsan Otomotiv A.Ş.", "OTKAR": "Otokar Otomotiv A.Ş.", "TOASO": "Tofaş A.Ş.", "TTRAK": "Türk Traktör A.Ş."},
    "Enerji ve Petrol": {"AHGAZ": "Ahlatcı Doğal Gaz Dağıtım Enerji ve Yatırım A.Ş.", "AKSEN": "Aksa Enerji Üretim A.Ş.", "ALFAS": "Alfa Solar Enerji Sanayi ve Ticaret A.Ş.", "ASTOR": "Astor Enerji A.Ş.", "ENJSA": "Enerjisa Enerji A.Ş.", "IPEKE": "İpek Doğal Enerji A.Ş.", "ODAS": "Odaş Elektrik Üretim A.Ş.", "SMRTG": "Smart Güneş Enerjisi A.Ş.", "TUPRS": "Türkiye Petrol Rafinerileri A.Ş.", "ZOREN": "Zorlu Enerji A.Ş."},
    "Demir-Çelik, Maden ve Metal": {"CEMTS": "Çemtaş Çelik Makina Sanayi A.Ş.", "EREGL": "Ereğli Demir ve Çelik Fabrikaları T.A.Ş.", "ISDMR": "İskenderun Demir ve Çelik A.Ş.", "KOZAA": "Koza Anadolu Metal Madencilik A.Ş.", "KOZAL": "Koza Altın İşletmeleri A.Ş.", "KRDMD": "Kardemir (D)"},
    "Kimya, Plastik ve İlaç": {"AKSA": "Aksa Akrilik Kimya Sanayii A.Ş.", "GENIL": "Gen İlaç ve Sağlık Ürünleri A.Ş.", "GUBRF": "Gübre Fabrikaları T.A.Ş.", "HEKTS": "Hektaş Ticaret T.A.Ş.", "PETKM": "Petkim Petrokimya Holding A.Ş.", "SASA": "Sasa Polyester A.Ş."},
    "Perakende, Gıda ve İçecek": {"AEFES": "Anadolu Efes Biracılık ve Malt Sanayii A.Ş.", "BIMAS": "BİM Birleşik Mağazalar A.Ş.", "CCOLA": "Coca-Cola İçecek A.Ş.", "MGROS": "Migros Ticaret A.Ş.", "SOKM": "Şok Marketler A.Ş.", "ULKER": "Ülker Bisküvi Sanayi A.Ş.", "YYLGD": "Yayla Agro Gıda A.Ş."},
    "Çimento, İnşaat ve Seramik": {"AKCNS": "Akçansa Çimento Sanayi ve Ticaret A.Ş.", "BTCIM": "Batıçim Batı Anadolu Çimento Sanayii A.Ş.", "BSOKE": "Batısöke Söke Çimento Sanayii T.A.Ş.", "CIMSA": "Çimsa Çimento Sanayi ve Ticaret A.Ş.", "ENKAI": "Enka İnşaat ve Sanayi A.Ş.", "KLSER": "Kaleseramik A.Ş.", "QUAGR": "Qua Granite A.Ş."},
    "Teknoloji, Bilişim ve İletişim": {"AGROT": "Agrotech Yüksek Teknoloji ve Yatırım A.Ş.", "ARDYZ": "ARD Bilişim Teknolojileri A.Ş.", "ASELS": "Aselsan Elektronik Sanayi ve Ticaret A.Ş.", "MIATK": "Mia Teknoloji A.Ş.", "TCELL": "Turkcell İletişim Hizmetleri A.Ş."},
    "Gayrimenkul Yatırım (GYO)": {"AKFGY": "Akfen Gayrimenkul Yatırım Ortaklığı A.Ş.", "AVPGY": "Avrupakent GYO A.Ş.", "EKGYO": "Emlak Konut GYO A.Ş.", "ISGYO": "İş GYO A.Ş."},
    "Dayanıklı Tüketim, Cam ve Tekstil": {"ARCLK": "Arçelik A.Ş.", "MAVI": "Mavi Giyim Sanayi ve Ticaret A.Ş.", "SISE": "Türkiye Şişe ve Cam Fabrikaları A.Ş.", "VESTL": "Vestel Elektronik A.Ş."},
    "Sigorta ve Emeklilik": {"ANSGR": "Anadolu Sigorta A.Ş.", "ANHYT": "Anadolu Hayat Emeklilik A.Ş."},
    "Savunma Sanayii": {"ALTNY": "Altınay Savunma Teknolojileri A.Ş."}
}

def sektor_bul(hisse_kodu):
    for sektor_adi, hisseler in BIST_HISSELER.items():
        if hisse_kodu in hisseler:
            return sektor_adi
    return "Bilinmiyor"

# --- 2. VERİ MOTORU ---
@st.cache_data(ttl=3600)
def veri_hazirla(hisse_kodu):
    try:
        yf_kodu = f"{hisse_kodu}.IS"
        hisse = yf.Ticker(yf_kodu)
        info = hisse.info
        
        if not info or 'longName' not in info:
            return None

        try:
            taze_veri = hisse.history(period="1d")
            guncel_fiyat = round(taze_veri['Close'].iloc[-1], 2) if not taze_veri.empty else round(info.get("currentPrice", 0), 2)
        except:
            guncel_fiyat = "N/A"

        gercek_sektor = sektor_bul(hisse_kodu)

        hisse_haber_listesi = rss_haber_cek(f"{hisse_kodu} hisse haber", limit=15)
        sektor_haber_listesi = rss_haber_cek(f"{gercek_sektor} sektörü ekonomi borsa", limit=15)

        return {
            "ad": info.get("longName", "N/A"),
            "sektor": gercek_sektor,
            "fiyat": guncel_fiyat,
            "hisse_haberleri": hisse_haber_listesi,
            "sektor_haberleri": sektor_haber_listesi
        }
    except Exception as e:
        return None

# --- 3. YAN PANEL (SIDEBAR) TASARIMI ---
st.sidebar.markdown("<br>", unsafe_allow_html=True)
col1, col2 = st.sidebar.columns(2)
with col1:
    if st.button("1", use_container_width=True): st.session_state.sayfa = 1
with col2:
    if st.button("2", use_container_width=True): st.session_state.sayfa = 2

st.sidebar.markdown("---")
st.sidebar.title("🔍 BİST 100 Tarayıcı")

secilen_sektor = st.sidebar.selectbox("Sektör Filtresi:", list(BIST_HISSELER.keys()))
hisse_sozlugu = BIST_HISSELER[secilen_sektor]
hisse_secenekleri = [f"{kod} - {isim}" for kod, isim in hisse_sozlugu.items()]

st.sidebar.selectbox("Hisse Seçin:", options=hisse_secenekleri, key="sektor_kutusu", on_change=sektor_secimi_guncelle)
tum_hisseler = sorted([f"{kod} - {isim}" for sektor, hisseler in BIST_HISSELER.items() for kod, isim in hisseler.items()])
st.sidebar.selectbox("Hızlı Arama:", options=tum_hisseler, index=None, placeholder="Kodu veya tam adı yazın...", key="arama_kutusu", on_change=arama_temizle_ve_sec)

secilen_kod = st.session_state.ana_hisse.split(" - ")[0]
secilen_tam_isim = st.session_state.ana_hisse.split(" - ")[1]

st.sidebar.markdown("---")
st.sidebar.caption("Borsa Analiz (Kappo) v3.5")

# --- 4. ANA EKRAN YÖNETİMİ ---
st.title("📈 Borsa Analiz (Kappo)")
st.markdown("---")

v = veri_hazirla(secilen_kod)

if v:
    # --- SAYFA 1: HABER AKIŞI ---
    if st.session_state.sayfa == 1:
        st.header(f"{secilen_tam_isim} ({secilen_kod})")
        st.caption(f"**Sektör:** {v['sektor']} | **Güncel Fiyat:** {v['fiyat']} TL")
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        st.subheader(f"📰 {secilen_kod} Hisse Haberleri")
        if v['hisse_haberleri']:
            for i, haber in enumerate(v['hisse_haberleri'][:3]):
                haber_karti_olustur(haber, "mavi", expander_icinde=False)
                
            if len(v['hisse_haberleri']) > 3:
                with st.expander("... Daha Fazla Hisse Haberi Göster"):
                    for haber in v['hisse_haberleri'][3:]:
                        haber_karti_olustur(haber, "mavi", expander_icinde=True)
        else:
            st.write("Bu hisse için son günlerde yeni bir gelişme bulunamadı.")
                    
        st.markdown("---")

        st.subheader(f"🏢 {v['sektor']} Sektörü Gelişmeleri")
        if v['sektor_haberleri']:
            for i, haber in enumerate(v['sektor_haberleri'][:3]):
                haber_karti_olustur(haber, "sari", expander_icinde=False)
                
            if len(v['sektor_haberleri']) > 3:
                with st.expander("... Daha Fazla Sektör Haberi Göster"):
                    for haber in v['sektor_haberleri'][3:]:
                        haber_karti_olustur(haber, "sari", expander_icinde=True)
        else:
            st.write("Bu sektör için son günlerde yeni bir gelişme bulunamadı.")

        st.markdown("---")

        # ÖNCE ESKİ BLOOMBERG HT BÖLÜMÜ (Yeşil ve Kolonlu)
        st.subheader(f"🔴 Bloomberg HT Son Dakika Haberleri")
        st.caption("Piyasanın genel yönünü belirleyen en güncel makro gelişmeler.")
        
        bloomberg_haberler = bloomberg_ht_cek(limit=30)
        
        # Karşılaştırma için şu anki saati UTC+3 (Türkiye Saati) olarak alıyoruz
        suan = datetime.now(timezone.utc).astimezone(TR_TZ)
        
        if bloomberg_haberler:
            b_ilk_alti = bloomberg_haberler[:6]
            b_kalanlar = bloomberg_haberler[6:]
            
            b_col1, b_col2 = st.columns(2)
            for i, haber in enumerate(b_ilk_alti):
                sira_numarasi = i + 1 
                if i % 2 == 0:
                    with b_col1:
                        haber_karti_olustur(haber, "yesil", sira_no=sira_numarasi, expander_icinde=False)
                else:
                    with b_col2:
                        haber_karti_olustur(haber, "yesil", sira_no=sira_numarasi, expander_icinde=False)
            
            son_24_saatteki_haberler = [h for h in b_kalanlar if (suan - h['dt_obj']).total_seconds() <= 86400]
            
            if son_24_saatteki_haberler:
                with st.expander(f"... Daha Fazla Son Dakika Göster (Son 24 Saatte {len(son_24_saatteki_haberler)} Haber)"):
                    for i, haber in enumerate(son_24_saatteki_haberler):
                        devam_sirasi = i + 7 
                        haber_karti_olustur(haber, "yesil", sira_no=devam_sirasi, expander_icinde=True)
        else:
            st.write("Şu an son dakika haberi çekilemiyor.")
            
        st.markdown("---")
        
        # YENİ EKLENEN BLOOMBERG HT BÖLÜMÜ (Kırmızı ve Minimal)
        st.subheader(f"Bloomberg HT Son Dakika")
        st.caption("Günün öne çıkan finansal akışı.")
        
        if bloomberg_haberler:
            for i, haber in enumerate(b_ilk_alti):
                sira_numarasi = i + 1 
                bloomberg_karti_olustur(haber, sira_no=sira_numarasi, expander_icinde=False)
                
            if son_24_saatteki_haberler:
                with st.expander(f"... Tüm Canlı Akışı Göster"):
                    for i, haber in enumerate(son_24_saatteki_haberler):
                        devam_sirasi = i + 7 
                        bloomberg_karti_olustur(haber, sira_no=devam_sirasi, expander_icinde=True)
        else:
            st.write("Şu an canlı akış çekilemiyor.")

    # --- SAYFA 2: KAPPO AGENT SOHBETİ ---
    elif st.session_state.sayfa == 2:
        st.header(f"🤖 Kappo ile Sohbet: {secilen_kod}")
        st.caption(f"Şu an **{secilen_tam_isim}** hissesi özelinde **Gemini 2.5 Flash** ile analiz yapıyoruz.")
        
        aktif_model_kodu = "gemini-2.5-flash"
        guncel_haberler = " | ".join([h["baslik"] for h in v['hisse_haberleri'][:5]]) if v['hisse_haberleri'] else "Yeni haber yok."
        
        sistem_mesaji = f"Senin adın Kappo. Profesyonel, net ve yardımcı bir finansal yapay zeka asistanısın. Şu an Türkiye borsasındaki {secilen_kod} ({secilen_tam_isim}) hissesini inceliyorsun. Sektör: {v['sektor']}, Fiyat: {v['fiyat']} TL. Piyasaya düşen son güncel haberler şunlar: '{guncel_haberler}'. KESİNLİKLE her mesaja 'Merhaba ben Kappo' diye başlama. Kendini tanıtmayı bırak ve sadece sorulan soruya net, analitik bir cevap ver."
        
        aktif_ai_model = genai.GenerativeModel(model_name=aktif_model_kodu, system_instruction=sistem_mesaji)
        st.markdown("---")

        if "aktif_hisse" not in st.session_state or st.session_state.aktif_hisse != secilen_kod or "mesajlar_ui" not in st.session_state:
            st.session_state.aktif_hisse = secilen_kod
            st.session_state.mesajlar_ui = [{"role": "assistant", "content": f"Merhaba! Şu an **{secilen_kod}** ({v['sektor']} sektörü) hissesini inceliyoruz. Güncel fiyatı {v['fiyat']} TL. Bana hisseyle ilgili ne sormak istersin?"}]
            st.session_state.api_gecmis = []

        for mesaj in st.session_state.mesajlar_ui:
            with st.chat_message(mesaj["role"]):
                st.markdown(mesaj["content"])

        if prompt := st.chat_input(f"{secilen_kod} hakkında bir şey sor..."):
            st.session_state.mesajlar_ui.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            api_ye_gidecek_veriler = st.session_state.api_gecmis + [{"role": "user", "parts": [prompt]}]

            with st.chat_message("assistant"):
                with st.spinner(f"Kappo analiz yapıyor..."):
                    try:
                        yanit = aktif_ai_model.generate_content(api_ye_gidecek_veriler)
                        st.markdown(yanit.text)
                        
                        st.session_state.mesajlar_ui.append({"role": "assistant", "content": yanit.text})
                        st.session_state.api_gecmis.append({"role": "user", "parts": [prompt]})
                        st.session_state.api_gecmis.append({"role": "model", "parts": [yanit.text]})
                    except Exception as e:
                        st.error(f"Kappo ile iletişim kurulamadı. Hata Detayı: {e}")

else:
    st.error(f"⚠️ {secilen_kod} için veri çekilemedi. Yahoo Finance geçici olarak yanıt vermiyor olabilir veya hisse kodu hatalı.")
