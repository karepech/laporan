import requests
import cloudscraper
import gzip
import xml.etree.ElementTree as ET
import re
import difflib
import concurrent.futures
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from io import BytesIO

# ========================================================
# 1. KONFIGURASI URL UTAMA
# ========================================================
M3U_URLS = [
    "https://aspaltvpasti.top/xxx/merah.php",
    "https://deccotech.online/tv/tvstream.html", 
    "https://freeiptv2026.tsender57.workers.dev", 
    "https://raw.githubusercontent.com/tvplaylist/T2/refs/heads/main/tv1",
    "http://sauridigital.my.id/kerbaunakal/2026TVGNS.html", 
    "https://raw.githubusercontent.com/mimipipi22/lalajo/refs/heads/main/playlist25",
    "https://semar25.short.gy",
    "https://bit.ly/TVKITKAT",
    "https://liveevent.iptvbonekoe.workers.dev",
    "https://bwifi.my.id/lokal",
    "https://bit.ly/KPL203"
]
EPG_URLS = [
    "https://raw.githubusercontent.com/AqFad2811/epg/main/indonesia.xml",
    "https://epgshare01.online/epgshare01/epg_ripper_ALL_SPORTS.xml.gz",
    "https://epg.pw/xmltv/epg.xml.gz"
]

MAP_URL = "https://raw.githubusercontent.com/karepech/bakul/refs/heads/main/map.txt"
OUTPUT_FILE = "playlist_termapping.m3u"
LINK_STANDBY = "https://bwifi.my.id/live.mp4" 
LINK_UPCOMING = "https://bwifi.my.id/5menit.mp4" 

GLOBAL_SEEN_STREAM_URLS = set()
COMPILED_MAPPING = []

# ========================================================
# 2. MESIN MAPPING & PENERJEMAH BAHASA
# ========================================================
def load_mapping():
    print("Mendownload kamus mapping...")
    try:
        r = requests.get(MAP_URL, timeout=30).text
        MAPPING_DICT = {}
        for line in r.splitlines():
            line = line.split('#')[0].strip() 
            if not line or line.startswith('['): continue
            if '=' in line:
                official, aliases = line.split('=', 1)
                official = official.strip().lower()
                for alias in aliases.split(','):
                    alias = alias.strip().lower()
                    if alias: MAPPING_DICT[alias] = official
        
        sorted_map = dict(sorted(MAPPING_DICT.items(), key=lambda x: len(x[0]), reverse=True))
        for alias, official in sorted_map.items():
            COMPILED_MAPPING.append((re.compile(r'\b' + re.escape(alias) + r'\b'), official))
    except Exception as e:
        print(f"❌ Gagal memuat map.txt: {e}")

@lru_cache(maxsize=10000) 
def rumus_samakan_teks(teks):
    if not teks: return ""
    teks = teks.lower()
    for pattern, official in COMPILED_MAPPING:
        teks = pattern.sub(official, teks)
    teks = re.sub(r'\b(sports|sport|tv|hd|fhd|sd|4k|ch|channel|network)\b', '', teks)
    teks = re.sub(r'\[.*?\]|\(.*?\)', '', teks)
    teks = re.sub(r'[^a-z0-9]', '', teks)
    return teks

CACHE_FUZZY = {}

@lru_cache(maxsize=5000)
def terjemahkan_bahasa(title):
    t = title
    kamus_asing = {
        "fudbal": "Sepakbola", "nogomet": "Sepakbola", "odbojka": "Voli", "košarka": "Basket",
        "italijanska liga": "Liga Italia", "engleska liga": "Liga Inggris", 
        "španska liga": "Liga Spanyol", "francuska liga": "Liga Prancis",
        "nemačka liga": "Liga Jerman", "njemačka liga": "Liga Jerman",
        "liga prvaka": "Liga Champions", "liga prvakov": "Liga Champions",
        "evropska liga": "Liga Europa", "europska liga": "Liga Europa",
        "zlatna liga": "Liga Emas", "rukomet": "Bola Tangan", "hokej": "Hoki",
        "tenis": "Tenis", "piłka nożna": "Sepakbola"
    }
    for asing, indo in kamus_asing.items():
        t = re.sub(r'(?i)\b' + asing + r'\b', indo, t)
    t = re.sub(r'^([A-Za-z0-9\s]+)\s+-\s+([A-Za-z0-9\s]+)([\.,]|$)', r'\1 vs \2\3', t)
    return t

# ========================================================
# 3. ATURAN SULTAN, FILTER BENUA & BUKU SEJARAH
# ========================================================
REGEX_LIVE = re.compile(r'(?i)(\(l\)|\[l\]|\(d\)|\[d\]|\(r\)|\[r\]|\blive\b|\blangsung\b|\blive on\b)')
REGEX_VS = re.compile(r'\b(vs|v)\b')
REGEX_NON_ALPHANUM = re.compile(r'[^a-z0-9]')
REGEX_EVENT = re.compile(r'(?:^|[^0-9])(\d{2})[:\.](\d{2})\s*(?:WIB)?\s*[\-\|]?\s*(.+)', re.IGNORECASE)

@lru_cache(maxsize=5000)
def bersihkan_judul_event(title):
    bersih = REGEX_LIVE.sub('', title)
    bersih = re.sub(r'^[\-\:\,\|]\s*', '', re.sub(r'\s+', ' ', bersih)).strip()
    return terjemahkan_bahasa(bersih)

def generate_event_key(title, timestamp):
    tc = re.sub(r'(?i)\#\s*\d+|\[.*?\]|\(.*?\)', '', title)
    tc = re.sub(r'\d+\]?$', '', tc.strip())
    return f"{REGEX_NON_ALPHANUM.sub('', REGEX_VS.sub('', tc.lower()))}_{timestamp}"

@lru_cache(maxsize=2000)
def get_vip_score(ch_name):
    n = ch_name.lower()
    if any(k in n for k in ['bein', 'spotv', 'sportstars', 'soccer channel', 'champions tv', 'rcti sports']): return 0
    return 1

@lru_cache(maxsize=5000)
def get_flag(m3u_name):
    n = m3u_name.lower()
    if any(x in n for x in [' us', 'usa', 'america']): return "🇺🇸" 
    if any(x in n for x in [' sg', 'starhub', 'singapore']): return "🇸🇬"
    if any(x in n for x in [' my', 'malaysia']): return "🇲🇾"
    if any(x in n for x in [' en', 'english', ' uk', 'sky']): return "🇬🇧"
    if any(x in n for x in [' th', 'thai', 'true']): return "🇹🇭"
    if any(x in n for x in [' hk', 'hong']): return "🇭🇰"
    if any(x in n for x in [' au', 'optus', 'aus']): return "🇦🇺"
    if any(x in n for x in [' ae', 'arab', 'mena', 'ssc', 'alkass']): return "🇸🇦"
    if any(x in n for x in [' za', 'supersport', 'africa']): return "🇿🇦"
    if any(x in n for x in [' id', 'indo', 'indonesia']): return "🇮🇩"
    if 'bein' in n and not any(x in n for x in [' us', ' sg', ' my', ' uk', ' th', ' hk', ' au', ' ae', ' za']): return "🇮🇩"
    return "📺"

@lru_cache(maxsize=5000)
def get_region_ktp(name, epg_id=""):
    n = (name + " " + epg_id).lower()
    for reg, kws in [("US",['.us',' us','usa']), ("AU",['.au',' au','aus']), ("UK",['.uk',' uk','eng']), ("ARAB",['.ae',' ar','arab']), ("MY",['.my',' my','malaysia']), ("TH",['.th',' th','thai']), ("SG",['.sg',' sg','singapore']), ("ZA",['.za',' za','supersport']), ("HK",['.hk',' hk','hong']), ("PH",['.ph',' ph','phil']), ("ID",['.id',' id','indo'])]:
        if any(x in n for x in kws): return reg
    return "UNKNOWN"

@lru_cache(maxsize=5000)
def is_target_sport_channel(name):
    n = name.lower()
    sampah = ['movie', 'cinema', 'film', 'drama', 'kids', 'news', 'music']
    if any(x in n for x in sampah): return False
    target = ['sport', 'bein', 'spotv', 'liga', 'league', 'champions', 'premier', 'serie a', 'bundesliga', 'la liga', 'badminton', 'bwf', 'motogp', 'f1', 'nba', 'nfl', 'mls', 'basket', 'voli', 'tennis', 'rugby', 'afc', 'ssc', 'rcti', 'sctv', 'mnc', 'indosiar', 'inews']
    return any(t in n for t in target)

@lru_cache(maxsize=5000)
def is_allowed_sport(title, durasi_menit):
    t = title.lower()
    if re.search(r'[А-Яа-яЁё\u4e00-\u9fff\u3040-\u30ff\u0600-\u06ff]', t) or durasi_menit <= 30: return False
    haram_simbol = ["(d)", "[d]", "(r)", "[r]", "(c)", "[c]", "hls", "hl ", "h/l", "rev ", "rep ", "del "]
    if any(s in t for s in haram_simbol): return False
    haram_kata = ["replay", "delay", "re-run", "rerun", "recorded", "archives", "classic", "rewind", "encore", "highlights", "best of", "compilation", "collection", "pre-match", "post-match", "build-up", "build up", "preview", "review", "road to", "kick-off show", "warm up", "magazine", "studio", "talk", "show", "update", "weekly", "planet", "mini match", "mini", "life", "documentary", "tunda", "siaran tunda", "tertunda", "ulang", "siaran ulang", "tayangan ulang", "ulangan", "rakaman", "cuplikan", "sorotan", "rangkuman", "ringkasan", "kilas", "lensa", "jurnal", "terbaik", "pilihan", "pemanasan", "menuju kick off", "pra-perlawanan", "pasca-perlawanan", "sepak mula", "dokumenter", "obrolan", "bincang", "berita", "news", "apa kabar", "religi", "quran", "mekkah", "masterchef", "cgtn", "arirang", "cnn", "lfctv", "mutv", "chelsea tv", "re-live", "relive", "history", "retro", "memories", "greatest", "wwe", "ufc", "mma", "boxing", "fight", "fightesport", "esport", "e-sport", "smackdown", "raw", "one championship", "golf", "snooker", "biliar", "billiard", "panahan", "archery", "renang", "swimming", "sepeda", "cycling", "gulat", "darts", "atletik", "athletics", "gymnastic"]
    if re.search(r'\b(?:' + '|'.join(haram_kata) + r')\b', t): return False
    target_kws = ['vs', 'liga', 'league', 'cup', 'copa', 'championship', 'badminton', 'bwf', 'thomas', 'uber', 'sudirman', 'motogp', 'moto2', 'moto3', 'f1', 'formula', 'wsbk', 'nba', 'nfl', 'mls', 'basket', 'voli', 'volley', 'tennis', 'tenis', 'rugby', 'baseball', 'afc', 'afcon', 'concacaf', 'sudamericana', 'libertadores', 'premier', 'serie a', 'bundesliga', 'la liga']
    if not any(k in t for k in target_kws): return False
    return True

@lru_cache(maxsize=5000)
def is_valid_time_continent(w, title, ch_name):
    t = (title + " " + ch_name).lower()
    if any(k in t for k in [' uk', 'england', 'sky', 'euro', 'uefa', 'champions league', 'la liga', 'serie a', 'bundesliga', 'prancis', 'epl', 'premier league']):
        if 5.1 <= w <= 17.9: return False
    if any(k in t for k in ['us ', 'usa', 'america', 'mls', 'nba', 'nfl', 'concacaf', 'libertadores', 'sudamericana', 'copa', 'brasil', 'argentina', 'mexico']):
        if w > 14.0 or w < 5.0: return False
    if any(k in t for k in ['my', 'malaysia', 'sg', 'singapore', 'th ', 'thai', 'hk', 'hong', 'id ', 'indo', 'arab', 'saudi', 'afc', 'j-league', 'k-league', 'liga 1']):
        if 1.1 <= w <= 10.9: return False
    if any(k in t for k in ['au ', 'aus', 'optus', 'a-league', 'nbl']):
        if w > 18.0 or w < 7.0: return False
    if any(k in t for k in ['za ', 'africa', 'supersport', 'caf', 'afcon']):
        if 4.1 <= w <= 18.9: return False
    return True

def parse_time(ts, default_offset_hours=0):
    if not ts: return None
    try:
        # 1. Jika EPG sudah punya timezone spesifik (contoh: +0000, +0700)
        if len(ts) >= 19 and ('+' in ts or '-' in ts):
            dt = datetime.strptime(ts[:20].strip(), "%Y%m%d%H%M%S %z")
            return dt.astimezone(timezone(timedelta(hours=7))).replace(tzinfo=None)
        
        # 2. Jika EPG TIDAK PUNYA timezone
        dt_naive = datetime.strptime(ts[:14], "%Y%m%d%H%M%S")
        
        # Penyesuaian ke WIB (UTC+7) dengan mengkalkulasi offset lokal bawaan file
        dt_wib = dt_naive + timedelta(hours=(7 - default_offset_hours))
        return dt_wib
    except: return None

def fetch_url(url, is_epg):
    headers = {'Cache-Control': 'no-cache', 'Pragma': 'no-cache'}
    try:
        if "epgshare" in url:
            scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
            resp = scraper.get(url, timeout=45)
        else:
            resp = requests.get(url, headers=headers, timeout=45)
            
        if is_epg:
            if b'<html' in resp.content[:20].lower(): return url, None, True
            content = gzip.GzipFile(fileobj=BytesIO(resp.content)).read() if url.endswith('.gz') else resp.content
            return url, content, True
        else:
            return url, resp.text, False
    except Exception as e:
        print(f"❌ Gagal Download {url}: {e}")
        return url, None, is_epg

def get_provider_name(url):
    return url.split('/')[-1].upper()

# ========================================================
# 4. EKSEKUSI GABUNGAN
# ========================================================
load_mapping() 

now_wib = datetime.utcnow() + timedelta(hours=7)
limit_date = now_wib + timedelta(hours=24) 
limit_past = now_wib - timedelta(days=2) 

epg_dict = {} 
kamus_rumus_epg = {}
jadwal_dict = {} 
buku_sejarah_replay = set() 

print("1. Mendownload EPG dan M3U secara serentak (Turbo Mode)...")
epg_contents = {}
m3u_contents = {}

with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
    futures = [executor.submit(fetch_url, url, True) for url in EPG_URLS]
    futures += [executor.submit(fetch_url, url, False) for url in M3U_URLS]
    
    for future in concurrent.futures.as_completed(futures):
        url, content, is_epg = future.result()
        if content:
            if is_epg: epg_contents[url] = content
            else: m3u_contents[url] = content

print("2. Memproses Data EPG (Streaming Memory & Adaptasi Zona Waktu Lokal)...")
for url, content in epg_contents.items():
    
    # --- DETEKSI WAKTU LOKAL EPG SANA ---
    offset_sana = 0 # Default anggap UTC (seperti epgshare atau epg.pw)
    if "AqFad2811" in url or "indonesia.xml" in url:
        offset_sana = 7 # Anggap waktu lokal EPG ini sudah murni WIB (UTC+7)
        
    try:
        context = ET.iterparse(BytesIO(content), events=('end',))
        for event, elem in context:
            if elem.tag == 'channel':
                id_asli = elem.get('id')
                nama_epg = elem.findtext('display-name') or id_asli
                if id_asli:
                    epg_dict[id_asli] = nama_epg
                    kamus_rumus_epg[rumus_samakan_teks(id_asli)] = id_asli
                    kamus_rumus_epg[rumus_samakan_teks(nama_epg)] = id_asli
                elem.clear() # BEBASKAN RAM
                
            elif elem.tag == 'programme':
                cid = elem.get('channel')
                if cid not in epg_dict:
                    elem.clear()
                    continue
                
                title_elem = elem.find("title")
                title = title_elem.text if title_elem is not None else ""
                
                # --- PANGGIL PARSE TIME DENGAN OFFSET LOKAL SANA ---
                st = parse_time(elem.get("start"), offset_sana)
                sp = parse_time(elem.get("stop"), offset_sana)
                durasi = (sp - st).total_seconds() / 60 if st and sp else 0
                
                # FILTERING CEPAT: Jika bukan olahraga, langsung buang dari RAM!
                if st and sp and is_allowed_sport(title, durasi):
                    judul_bersih = bersihkan_judul_event(title).lower()
                    
                    if limit_past <= sp < now_wib:
                        if " vs " in judul_bersih or " v " in judul_bersih or len(judul_bersih.split()) >= 3:
                            buku_sejarah_replay.add(judul_bersih)
                    elif sp > now_wib and st < limit_date:
                        if judul_bersih not in buku_sejarah_replay:
                            w = st.hour + (st.minute / 60.0)
                            if is_valid_time_continent(w, title, epg_dict[cid]):
                                if cid not in jadwal_dict: jadwal_dict[cid] = []
                                icon_elem = elem.find("icon")
                                logo = icon_elem.get("src") if icon_elem is not None else ""
                                jadwal_dict[cid].append({
                                    "title": bersihkan_judul_event(title),
                                    "start": st, "stop": sp, 
                                    "live": (st - timedelta(minutes=5)) <= now_wib < sp,
                                    "logo": logo
                                })
                elem.clear() # BEBASKAN RAM
    except Exception as e:
        print(f"❌ Gagal Parse EPG {url}: {e}")

daftar_teks_epg_dirumus = list(kamus_rumus_epg.keys())
keranjang_match = {}
audit_m3u = {}

print("3. Mencocokkan M3U dengan Jadwal Sultan & Audit Laporan Berwarna...")
for url in M3U_URLS:
    provider_name = get_provider_name(url)
    audit_m3u[provider_name] = [] 
    
    content = m3u_contents.get(url)
    if not content: continue
    
    try:
        m3u_lines = content.splitlines()
        block = []
        for ln in m3u_lines:
            ln = ln.strip()
            if not ln or "EXTM3U" in ln.upper(): continue
            if ln.startswith("#"): block.append(ln)
            else:
                if not block: continue
                raw_extinf = next((b for b in block if b.upper().startswith("#EXTINF")), "")
                extra_tags = [b for b in block if not b.upper().startswith("#EXTINF") and not b.upper().startswith("#EXTGRP")]
                block = []
                
                if not raw_extinf or "," not in raw_extinf: continue
                stream_url = ln
                raw_attrs, m3u_name = raw_extinf.split(",", 1)
                m3u_name = m3u_name.strip()
                
                ev_m = REGEX_EVENT.search(m3u_name)
                if not ev_m and not is_target_sport_channel(m3u_name):
                    continue 
                
                if stream_url in GLOBAL_SEEN_STREAM_URLS: continue
                GLOBAL_SEEN_STREAM_URLS.add(stream_url)
                
                logo_match = re.search(r'(?i)tvg-logo=["\']([^"\']*)["\']', raw_attrs)
                orig_logo = logo_match.group(1) if logo_match else ""
                skor_vip = get_vip_score(m3u_name)
                
                clean_attrs = re.sub(r'(?i)\s*(group-title|tvg-group|tvg-id|tvg-logo|tvg-name)=("[^"]*"|\'[^\']*\'|[^\s,]+)', '', raw_attrs).strip()
                if not clean_attrs.upper().startswith("#EXTINF"):
                    clean_attrs = "#EXTINF:-1 " + clean_attrs.replace('#EXTINF:-1', '').replace('#EXTINF:0', '').strip()

                if ev_m:
                    hh, mm = int(ev_m.group(1)), int(ev_m.group(2))
                    ev_title = re.sub(r'(?i)\#\s*\d+|\[.*?\]|\(.*?\)', '', ev_m.group(3)).strip()
                    ev_start = now_wib.replace(hour=hh, minute=mm, second=0, microsecond=0)
                    if ev_start < now_wib - timedelta(hours=4): ev_start += timedelta(days=1)
                    ev_stop = ev_start + timedelta(hours=2) 
                    
                    if ev_stop > now_wib and ev_start < limit_date:
                        is_live = (ev_start - timedelta(minutes=5)) <= now_wib < ev_stop
                        key = generate_event_key(ev_title, ev_start.timestamp())
                        if key not in keranjang_match: 
                            keranjang_match[key] = {"is_live": is_live, "sort": ev_start.timestamp(), "vip": skor_vip, "links": []}
                        
                        jam_tayang = f"{ev_start.strftime('%H:%M')}-{ev_stop.strftime('%H:%M')}"
                        if is_live:
                            judul = f"{get_flag(ev_title)} 🔴 {jam_tayang} WIB - {terjemahkan_bahasa(ev_title)}"
                            inf = f'{clean_attrs} group-title="🔴 SEDANG TAYANG" tvg-id="" tvg-logo="{orig_logo}", {judul}'
                            keranjang_match[key]["links"].append({"prio": 0, "data": [inf] + extra_tags + [stream_url]})
                        else:
                            judul = f"{get_flag(ev_title)} ⏳ {jam_tayang} WIB - {terjemahkan_bahasa(ev_title)}"
                            inf = f'#EXTINF:-1 group-title="📅 JADWAL HARI INI" tvg-logo="{orig_logo}", {judul}'
                            keranjang_match[key]["links"].append({"prio": 0, "data": [inf, f"{LINK_UPCOMING}?m={key}"]})
                        
                        audit_m3u[provider_name].append(f"🟣 **[EVENT]** {m3u_name} otomatis masuk jadwal")
                    else:
                        audit_m3u[provider_name].append(f"🟤 **[BASI]** {m3u_name} diblokir (KADALUARSA)")
                    continue

                tvg_id_match = re.search(r'tvg-id="([^"]*)"', raw_attrs)
                id_m3u = tvg_id_match.group(1).strip() if tvg_id_match else ""
                id_bawaan = id_m3u if id_m3u else m3u_name
                
                teks_m3u_dirumus = rumus_samakan_teks(id_bawaan) or rumus_samakan_teks(m3u_name)
                id_epg_terpilih = ""
                metode = ""
                kandidat_id = None
                
                if teks_m3u_dirumus in kamus_rumus_epg:
                    kandidat_id = kamus_rumus_epg[teks_m3u_dirumus]
                    metode = "EXACT"
                else:
                    if teks_m3u_dirumus not in CACHE_FUZZY:
                        CACHE_FUZZY[teks_m3u_dirumus] = difflib.get_close_matches(teks_m3u_dirumus, daftar_teks_epg_dirumus, n=3, cutoff=0.8)
                    mirip = CACHE_FUZZY[teks_m3u_dirumus]
                    for m in mirip:
                        temp_id = kamus_rumus_epg[m]
                        ktp_epg = get_region_ktp(epg_dict.get(temp_id, ""), temp_id)
                        ktp_m3u = get_region_ktp(m3u_name)
                        if 'bein' in temp_id.lower() or 'spotv' in temp_id.lower():
                            if (ktp_epg if ktp_epg != "UNKNOWN" else "ID") == (ktp_m3u if ktp_m3u != "UNKNOWN" else "ID"):
                                kandidat_id = temp_id
                                break
                        elif ktp_epg == "UNKNOWN" or ktp_m3u == "UNKNOWN" or ktp_epg == ktp_m3u:
                            kandidat_id = temp_id
                            break
                    if kandidat_id: metode = "FUZZY"
                            
                if kandidat_id:
                    if not ('bein' in kandidat_id.lower() or 'spotv' in kandidat_id.lower()):
                        ktp_epg = get_region_ktp(epg_dict.get(kandidat_id, ""), kandidat_id)
                        ktp_m3u = get_region_ktp(m3u_name)
                        if ktp_epg == "UNKNOWN" or ktp_m3u == "UNKNOWN" or ktp_epg == ktp_m3u:
                            id_epg_terpilih = kandidat_id
                    else:
                            id_epg_terpilih = kandidat_id

                if id_epg_terpilih and id_epg_terpilih in jadwal_dict:
                    punya_jadwal = False
                    for ev in jadwal_dict[id_epg_terpilih]:
                        punya_jadwal = True
                        key = generate_event_key(ev['title'], ev['start'].timestamp())
                        if key not in keranjang_match: 
                            keranjang_match[key] = {"is_live": ev['live'], "sort": ev['start'].timestamp(), "vip": skor_vip, "links": []}
                        
                        final_logo = ev["logo"] or orig_logo
                        jam_tayang = f"{ev['start'].strftime('%H:%M')}-{ev['stop'].strftime('%H:%M')}"
                        
                        if ev["live"]:
                            m_disp = re.sub(r'[\[\]\(\)]', '', m3u_name).strip()
                            judul = f"{get_flag(m3u_name)} 🔴 {jam_tayang} WIB - {ev['title']} [{m_disp}]"
                            inf = f'{clean_attrs} group-title="🔴 SEDANG TAYANG" tvg-id="{id_epg_terpilih}" tvg-logo="{final_logo}", {judul}'
                            keranjang_match[key]["links"].append({"prio": 1, "data": [inf] + extra_tags + [stream_url]})
                        else:
                            judul_pendek = f"{get_flag(m3u_name)} ⏳ {jam_tayang} WIB - {ev['title']}"
                            inf = f'#EXTINF:-1 group-title="📅 JADWAL HARI INI" tvg-logo="{final_logo}", {judul_pendek}'
                            keranjang_match[key]["links"].append({"prio": 1, "data": [inf, f"{LINK_UPCOMING}?m={key}"]})
                    
                    if punya_jadwal:
                        if metode == "FUZZY": audit_m3u[provider_name].append(f"🟡 **[FUZZY]** {m3u_name} cocok [fuzzy] ({id_epg_terpilih})")
                        else: audit_m3u[provider_name].append(f"🟢 **[EXACT]** {m3u_name} cocok ({id_epg_terpilih})")
                    else:
                        audit_m3u[provider_name].append(f"🔴 **[KOSONG]** {m3u_name} tidak ada jadwal target")
                else:
                    audit_m3u[provider_name].append(f"🔴 **[KOSONG]** {m3u_name} tidak cocok id epg")
                    
    except Exception as e:
        print(f"Error memproses M3U {url}: {e}")

print("4. Merender M3U Final...")
waktu_paling_awal = {}
for key, match in keranjang_match.items():
    nama_unik = key.rsplit('_', 1)[0]
    if nama_unik not in waktu_paling_awal:
        waktu_paling_awal[nama_unik] = match["sort"]
    else:
        if match["sort"] < waktu_paling_awal[nama_unik]:
            waktu_paling_awal[nama_unik] = match["sort"]

hasil_render = []
for key, match in keranjang_match.items():
    nama_unik = key.rsplit('_', 1)[0]
    if match["sort"] > waktu_paling_awal[nama_unik] + 10800: continue 

    links = match["links"]
    unique_links = { l["data"][-1]: l for l in links }.values() 
    sorted_links = sorted(unique_links, key=lambda x: x["prio"])
    
    max_take = 2 if match["is_live"] else 1
    for l in sorted_links[:max_take]:
        hasil_render.append({"order": 0 if match["is_live"] else 1, "sort": match["sort"], "vip": match["vip"], "data": l["data"]})

hasil_render.sort(key=lambda x: (x["order"], float(x["sort"]), x["vip"]))

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write(f'#EXTM3U name="🔴 BAKUL WIFI SPORTS"\n')
    if not hasil_render: 
        f.write(f'#EXTINF:-1 group-title="ℹ️ INFO", BELUM ADA PERTANDINGAN\n{LINK_STANDBY}\n')
    else:
        for it in hasil_render: 
            f.write("\n".join(it["data"]) + "\n")

with open("laporan_channel_m3u.md", "w", encoding="utf-8") as f:
    f.write("# LAPORAN AUDIT CHANNEL BAKUL WIFI SPORTS\n")
    f.write(f"**Diperbarui pada:** {now_wib.strftime('%d-%m-%Y %H:%M WIB')}\n\n")
    
    for provider, laporan in audit_m3u.items():
        f.write(f"### 📁 SUMBER: {provider}\n")
        
        if not laporan:
            f.write("- ⚪ Tidak ada channel olahraga target atau link mati.\n")
        else:
            laporan_sorted = sorted(laporan, key=lambda x: 0 if "🟢" in x or "🟡" in x or "🟣" in x else 1)
            for baris in laporan_sorted:
                f.write(f"- {baris}\n")
        f.write("\n---\n\n")

print(f"SELESAI! Skrip Ringan dan Waktu Super Presisi Dieksekusi!")
