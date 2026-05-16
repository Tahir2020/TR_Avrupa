#!/usr/bin/env python3

import json
import re
import subprocess
import sys
import requests
import random
import time
import urllib.parse
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

CONFIG_FILE = "config.json"
COOKIE_FILE = "cookies.txt"

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36"
)


def load_config() -> Dict:
    """config.json dosyasını yükler"""
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    if "channels" not in config or not isinstance(config["channels"], list):
        raise ValueError("config.json içinde 'channels' listesi bulunamadı.")

    if not config["channels"]:
        raise ValueError("config.json içinde kanal listesi boş.")

    config.setdefault("quality", "best[height<=1080][fps<=50]/best")
    config.setdefault("output_folder", "playlist")
    config.setdefault("output_playlist", "playlist.m3u8")
    config.setdefault("resolution", "1280x720")
    config.setdefault("bandwidth", "1280000")
    
    return config


def safe_filename(name: str) -> str:
    """Güvenli dosya adı oluşturur"""
    replacements = {
        "ç": "c", "Ç": "C",
        "ğ": "g", "Ğ": "G",
        "ı": "i", "İ": "I",
        "ö": "o", "Ö": "O",
        "ş": "s", "Ş": "S",
        "ü": "u", "Ü": "U",
    }
    for old, new in replacements.items():
        name = name.replace(old, new)

    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")
    return f"{name or 'channel'}.m3u8"


def is_direct_m3u8(url: str) -> bool:
    """URL'nin direkt m3u8 olup olmadığını kontrol eder"""
    clean = url.lower().split("?", 1)[0]
    return clean.endswith(".m3u8")


def is_atv_avrupa_name(name: str) -> bool:
    """ATV Avrupa kontrolü"""
    lower = name.lower()
    return "atv" in lower and "avrupa" in lower


def is_eurostar_name(name: str) -> bool:
    """EuroStar kontrolü"""
    lower = name.lower()
    return "euro star" in lower or "eurostar" in lower or "star avrupa" in lower


def is_show_turk_name(name: str) -> bool:
    """Show Türk kontrolü"""
    lower = name.lower()
    return "show" in lower and ("türk" in lower or "turk" in lower)


def load_netscape_cookies(cookie_file: str = COOKIE_FILE) -> Dict[str, str]:
    """Netscape format cookies.txt dosyasını requests cookies dict formatına çevirir"""
    cookies: Dict[str, str] = {}
    path = Path(cookie_file)

    if not path.exists():
        print(f"   ℹ️ {cookie_file} bulunamadı, cookiesiz devam ediliyor")
        return cookies

    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()

                if not line or line.startswith("#"):
                    continue

                parts = line.split("\t")
                if len(parts) >= 7:
                    name = parts[5].strip()
                    value = parts[6].strip()
                    if name:
                        cookies[name] = value

        if cookies:
            print(f"   🍪 {len(cookies)} cookie yüklendi")
        else:
            print("   ⚠️ cookies.txt var ama okunabilir cookie bulunamadı")

    except Exception as e:
        print(f"   ⚠️ Cookie okuma hatası: {e}")

    return cookies


def get_atv_avrupa_token() -> Optional[str]:
    """ATV Avrupa 576p - cookies.txt destekli otomatik token alıcı"""
    headers = {
        "X-isApp": "1",
        "X-Rand": str(int(time.time() * 1000)),
        "Origin": "https://www.atvavrupa.tv",
        "Referer": "https://www.atvavrupa.tv/",
        "User-Agent": CHROME_UA,
        "Accept": "*/*",
        "Accept-Language": "tr,en-US;q=0.9,en;q=0.8,de;q=0.7",
    }

    stream_url = "https://trkvz-live.ercdn.net/atvavrupa/atvavrupa_576p.m3u8"
    encoded = urllib.parse.quote(stream_url)
    token_url = (
        "https://securevideotoken.tmgrup.com.tr/webtv/secure"
        f"?{random.randint(1, 1000000)}&url={encoded}&url2={encoded}"
    )

    cookies = load_netscape_cookies()

    try:
        response = requests.get(
            token_url,
            headers=headers,
            cookies=cookies if cookies else None,
            timeout=15,
        )

        print(f"   ATV token status: {response.status_code}")
        response.raise_for_status()
        data = response.json()

        if data.get("Success") and data.get("Url"):
            token_url_result = data.get("Url")
            print("   ✅ ATV Avrupa token alındı")

            match = re.search(r"[?&]e=(\d+)", token_url_result)
            if match:
                expire = datetime.fromtimestamp(int(match.group(1)))
                print(f"   ⏰ ATV token süresi: {expire}")

            return token_url_result

        print(f"   ❌ ATV Avrupa token alınamadı: {data}")
        return None

    except Exception as e:
        print(f"   ❌ ATV Avrupa hatası: {e}")
        return None


def get_eurostar_token() -> Optional[str]:
    """EuroStar 1080p - HTML'den token çek"""
    headers = {
        "User-Agent": CHROME_UA,
        "Accept": "text/html,application/xhtml+xml",
    }

    page_url = "https://www.eurostartv.com.tr/canli-izle"

    try:
        response = requests.get(page_url, headers=headers, timeout=15)
        html = response.text

        pattern = r"var liveUrl = 'https://dygvideo\.dygdigital\.com/live/hls/staravrupa\?token=([a-f0-9]+)';"
        match = re.search(pattern, html)

        if not match:
            print("   ❌ EuroStar token HTML'de bulunamadı")
            return None

        token = match.group(1)
        token_url = f"https://dygvideo.dygdigital.com/live/hls/staravrupa?token={token}"

        headers2 = {
            "Origin": "https://www.eurostartv.com.tr",
            "Referer": "https://www.eurostartv.com.tr/",
            "User-Agent": CHROME_UA,
        }

        response2 = requests.get(token_url, headers=headers2, allow_redirects=False, timeout=10)

        if response2.status_code == 302:
            master_url = response2.headers.get("Location")
            if not master_url:
                print("   ❌ EuroStar Location header boş")
                return None

            match = re.match(r"(.*/)live\.m3u8\?(.*)", master_url)
            if match:
                stream_url = f"{match.group(1)}live_1080p3000000kbps/index.m3u8?{match.group(2)}"
                print("   ✅ EuroStar 1080p token alındı")
                return stream_url

            print("   ✅ EuroStar master URL alındı")
            return master_url

        print(f"   ❌ EuroStar redirect alınamadı: {response2.status_code}")
        return None

    except Exception as e:
        print(f"   ❌ EuroStar hatası: {e}")
        return None


def get_show_turk_token() -> Optional[str]:
    """Show Türk - otomatik token alıcı"""
    url = "https://www.showturk.com.tr/canli-yayin"
    pattern = r"playlist\.m3u8\?e=(\d+)&st=([^\"\s&]+)"

    headers = {
        "User-Agent": CHROME_UA,
        "Accept": "text/html,application/xhtml+xml",
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        html = response.text
        match = re.search(pattern, html)

        if match:
            e, st = match.groups()
            stream_url = f"https://ciner-live.ercdn.net/showturk/playlist.m3u8?e={e}&st={st}&tv=1"
            print("   ✅ Show Türk token alındı")
            return stream_url

        print("   ❌ Show Türk token bulunamadı")
        return None

    except Exception as e:
        print(f"   ❌ Show Türk hatası: {e}")
        return None


def get_youtube_stream_url(youtube_url: str, quality: str) -> Optional[str]:
    """YouTube stream URL'sini yt-dlp ile alır"""
    cmd = [
        "yt-dlp",
        "-g",
        "--cookies", COOKIE_FILE,
        "--js-runtimes", "deno",
        "--remote-components", "ejs:github",
        "--extractor-args", "youtube:player_client=default",
        "-f", quality,
        youtube_url,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )

        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        for line in lines:
            if "manifest" in line or ".m3u8" in line:
                return line

        if lines:
            return lines[0]

        return None

    except subprocess.CalledProcessError as e:
        print("❌ yt-dlp hatası:")
        print(e.stderr)
        return None
    except Exception as e:
        print(f"❌ Hata: {e}")
        return None


def get_stream_url(channel: Dict, quality: str) -> Optional[str]:
    """Kanal tipine göre stream URL'sini alır"""
    channel_name = channel.get("name", "")

    if is_atv_avrupa_name(channel_name):
        print("🔐 ATV Avrupa için token alınıyor...")
        return get_atv_avrupa_token()

    if is_eurostar_name(channel_name):
        print("🔐 EuroStar için token alınıyor...")
        return get_eurostar_token()

    if is_show_turk_name(channel_name):
        print("🔐 Show Türk için token alınıyor...")
        return get_show_turk_token()

    url = channel.get("url") or channel.get("youtube_url")

    if not url:
        return None

    if is_direct_m3u8(url):
        print("🔗 Direkt m3u8 linki kullanılıyor")
        return url

    print("🎬 YouTube stream alınıyor...")
    return get_youtube_stream_url(url, quality)


def create_hls_playlist(stream_url: str, resolution: str = "1280x720", bandwidth: str = "1280000") -> str:
    """
    HLS formatında M3U8 playlist oluşturur
    Format:
    #EXTM3U
    #EXT-X-VERSION:3
    #EXT-X-STREAM-INF:BANDWIDTH=1280000,RESOLUTION=1280x720
    stream_url
    """
    return (
        f"#EXTM3U\n"
        f"#EXT-X-VERSION:3\n"
        f"#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},RESOLUTION={resolution}\n"
        f"{stream_url}"
    )


def create_main_playlist_entry(channel: Dict, stream_url: str) -> str:
    """
    Ana playlist için EXTINF girişi oluşturur
    Format: #EXTINF:-1,Kanal Adı\nstream_url
    """
    name = channel["name"]
    return f"#EXTINF:-1,{name}\n{stream_url}"


def write_single_channel_file(channel: Dict, stream_url: str, output_folder: Path, resolution: str, bandwidth: str) -> Path:
    """Tek bir kanal için HLS formatında M3U8 dosyası oluşturur"""
    output_folder.mkdir(parents=True, exist_ok=True)
    filename = channel.get("m3u_file") or safe_filename(channel["name"])
    path = output_folder / filename

    # HLS formatında içerik oluştur
    content = create_hls_playlist(stream_url, resolution, bandwidth)
    path.write_text(content, encoding="utf-8")
    
    return path


def write_main_playlist(entries: List[str], output_folder: Path, output_playlist: str) -> Path:
    """Ana playlist dosyasını oluşturur"""
    output_folder.mkdir(parents=True, exist_ok=True)
    path = output_folder / output_playlist
    
    content = "#EXTM3U\n#EXT-X-VERSION:3\n"
    content += "\n".join(entries)
    
    path.write_text(content, encoding="utf-8")
    return path


def create_compatibility_links(output_folder: Path, main_playlist_name: str):
    """Eski workflow için uyumluluk linkleri oluşturur"""
    main_m3u8 = output_folder / main_playlist_name
    
    if main_m3u8.exists():
        # playerlist.m3u oluştur
        playerlist_m3u = output_folder / "playerlist.m3u"
        shutil.copy2(main_m3u8, playerlist_m3u)
        print(f"✅ Uyumluluk dosyası oluşturuldu: {playerlist_m3u}")
        
        # playerlist.m3u8 oluştur
        playerlist_m3u8 = output_folder / "playerlist.m3u8"
        if not playerlist_m3u8.exists():
            shutil.copy2(main_m3u8, playerlist_m3u8)
            print(f"✅ Uyumluluk dosyası oluşturuldu: {playerlist_m3u8}")


def main() -> int:
    print("=" * 60)
    print("🎬 TV Kanalları M3U8 Güncelleyici (HLS Formatında)")
    print("=" * 60)
    print(f"🕐 Başlangıç: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    try:
        config = load_config()
    except Exception as e:
        print(f"❌ Config okunamadı: {e}")
        return 1

    quality = config["quality"]
    output_folder = Path(config["output_folder"])
    output_playlist = config["output_playlist"]
    resolution = config.get("resolution", "1280x720")
    bandwidth = config.get("bandwidth", "1280000")

    # Çıktı klasörünü oluştur
    output_folder.mkdir(parents=True, exist_ok=True)

    # Eski dosyaları temizle (uyumluluk dosyaları hariç)
    for old_file in output_folder.glob("*.m3u8"):
        if old_file.name not in ["playerlist.m3u8"]:
            old_file.unlink()
    for old_file in output_folder.glob("*.m3u"):
        if old_file.name not in ["playerlist.m3u"]:
            old_file.unlink()

    playlist_entries: List[str] = []
    failed_channels: List[str] = []
    successful_channels: List[str] = []

    for index, channel in enumerate(config["channels"], start=1):
        name = channel.get("name", f"Kanal {index}")

        if not (channel.get("url") or channel.get("youtube_url")):
            print(f"\n⚠️ [{index}/{len(config['channels'])}] {name}: url/youtube_url yok, atlandı")
            failed_channels.append(name)
            continue

        print(f"\n🔄 [{index}/{len(config['channels'])}] {name} taranıyor...")
        print("-" * 40)
        
        stream_url = get_stream_url(channel, quality)

        if not stream_url:
            print(f"❌ {name}: Stream URL alınamadı")
            failed_channels.append(name)
            continue

        # Tek kanal dosyası oluştur (HLS formatında)
        single_file = write_single_channel_file(
            channel, stream_url, output_folder, resolution, bandwidth
        )
        
        # Ana playlist için entry
        playlist_entries.append(create_main_playlist_entry(channel, stream_url))
        
        successful_channels.append(name)
        print(f"✅ {name}: {single_file.name} oluşturuldu")
        print(f"   📹 Stream URL: {stream_url[:80]}..." if len(stream_url) > 80 else f"   📹 Stream URL: {stream_url}")
        
        # Rate limiting
        time.sleep(0.5)

    # Ana playlist'i oluştur
    if playlist_entries:
        main_playlist = write_main_playlist(playlist_entries, output_folder, output_playlist)
        print(f"\n{'=' * 60}")
        print(f"✅ Toplu liste oluşturuldu: {main_playlist}")
        print(f"✅ Başarılı kanal sayısı: {len(successful_channels)}/{len(config['channels'])}")
        
        # Uyumluluk linkleri oluştur
        create_compatibility_links(output_folder, output_playlist)
    else:
        print("\n❌ Hiçbir kanal için link alınamadı")
        return 1

    # Başarısız kanalları göster
    if failed_channels:
        print(f"\n⚠️ Alınamayan kanallar ({len(failed_channels)}):")
        for channel_name in failed_channels:
            print(f"   - {channel_name}")

    # Oluşturulan dosyaları listele
    print(f"\n📁 '{output_folder}/' klasörü içeriği:")
    print("-" * 40)
    
    m3u8_files = sorted(output_folder.glob("*.m3u8"))
    m3u_files = sorted(output_folder.glob("*.m3u"))
    
    for file in m3u8_files:
        size = file.stat().st_size
        print(f"   📺 {file.name} ({size} bytes)")
    
    for file in m3u_files:
        if file.name not in [f.name for f in m3u8_files]:
            size = file.stat().st_size
            print(f"   📄 {file.name} ({size} bytes)")

    # Örnek dosya içeriğini göster
    if m3u8_files:
        print(f"\n📄 Örnek dosya içeriği ({m3u8_files[0].name}):")
        print("-" * 40)
        sample_content = m3u8_files[0].read_text(encoding="utf-8")
        print(sample_content)

    print(f"\n{'=' * 60}")
    print(f"✅ İşlem tamamlandı: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
