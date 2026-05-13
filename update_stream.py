#!/usr/bin/env python3

import subprocess
import json
import sys
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional


def load_config() -> Dict:
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("❌ config.json bulunamadı!")
        sys.exit(1)


def check_cookie_file():
    """Cookie dosyasını kontrol et ve doğrula"""
    cookie_file = 'cookies.txt'
    
    if not os.path.exists(cookie_file):
        print("⚠️ cookies.txt dosyası bulunamadı!")
        return False
    
    size = os.path.getsize(cookie_file)
    if size < 100:
        print(f"⚠️ cookies.txt çok küçük ({size} byte) - geçersiz!")
        return False
    
    # Dosyanın içeriğini kontrol et
    with open(cookie_file, 'r') as f:
        content = f.read()
        if '# Netscape HTTP Cookie File' not in content and '.youtube.com' not in content:
            print("⚠️ cookies.txt geçersiz formatta!")
            return False
    
    print(f"✅ cookies.txt geçerli ({size} byte)")
    return True


def get_stream_url(youtube_url: str, quality: str) -> Optional[str]:
    """
    YouTube canlı yayın URL'sinden m3u8 manifest adresini alır
    """
    # Python yt-dlp module'ünü kullan (daha güvenilir)
    try:
        from yt_dlp import YoutubeDL
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'force_generic_extractor': False,
            'format': quality,
            'cookiefile': 'cookies.txt' if os.path.exists('cookies.txt') else None,
            'extractor_args': {
                'youtube': {
                    'player_client': ['web'],
                    'skip': ['hls', 'dash']
                }
            }
        }
        
        with YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(youtube_url, download=False)
                
                # Canlı yayın mı kontrol et
                if info.get('is_live'):
                    # Manifest URL'sini al
                    if 'hls_manifest_url' in info:
                        return info['hls_manifest_url']
                    elif 'url' in info:
                        return info['url']
                    elif 'formats' in info:
                        # En iyi formatı bul
                        for f in info['formats']:
                            if f.get('protocol') == 'm3u8_native':
                                return f.get('url')
                
                print("   📺 Yayın bulunamadı veya canlı değil")
                return None
                
            except Exception as e:
                error_msg = str(e)
                if 'Sign in' in error_msg:
                    print("   🔐 Oturum gerekli (cookies geçersiz)")
                elif 'Video unavailable' in error_msg:
                    print("   📺 Yayında değil")
                elif 'Private' in error_msg:
                    print("   🔒 Gizli video")
                else:
                    print(f"   ❌ {error_msg[:60]}")
                return None
                
    except ImportError:
        print("   ❌ yt-dlp module yok!")
        return None


def get_stream_url_subprocess(youtube_url: str, quality: str) -> Optional[str]:
    """
    Subprocess ile yt-dlp çağır (alternatif yöntem)
    """
    cmd = [
        'yt-dlp',
        '-g',
        '--cookies', 'cookies.txt',
        '--extractor-args', 'youtube:player_client=web',
        '-f', quality,
        '--no-check-certificate',
        youtube_url
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else ""
            
            if 'Sign in' in error_msg or 'cookies' in error_msg.lower():
                print("   🔐 Cookie hatası")
            elif 'Video unavailable' in error_msg:
                print("   📺 Yayında değil")
            else:
                short_err = error_msg.split('\n')[0][:50] if error_msg else "Hata"
                print(f"   ❌ {short_err}")
            return None
            
        stream_url = result.stdout.strip()
        if stream_url and ('.m3u8' in stream_url or 'googlevideo' in stream_url):
            return stream_url
            
        return None
        
    except Exception as e:
        print(f"   ❌ {str(e)[:40]}")
        return None


def save_channel_m3u(channel: Dict, stream_url: str) -> bool:
    if not stream_url:
        return False
    
    os.makedirs('output', exist_ok=True)
    
    safe_name = channel['channel_name'].replace(' ', '_').replace('/', '_').replace(':', '').replace('?', '').replace('(', '').replace(')', '')
    filename = os.path.join('output', f"{safe_name}.m3u")
    
    m3u_content = f"""#EXTM3U
#EXTINF:-1 tvg-id="{safe_name.lower()}" tvg-name="{channel['channel_name']}" tvg-logo="{channel['channel_logo']}" group-title="{channel['group_title']}", {channel['channel_name']}
{stream_url}
"""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(m3u_content)
        return True
    except Exception as e:
        return False


def save_master_playlist(channels_data: List[Dict], output_file: str) -> None:
    groups = {}
    for ch in channels_data:
        group = ch['group_title']
        if group not in groups:
            groups[group] = []
        groups[group].append(ch)
    
    successful = sum(1 for ch in channels_data if ch.get('stream_url'))
    
    m3u_content = "#EXTM3U\n"
    m3u_content += f"# Playlist: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    m3u_content += f"# Toplam: {len(channels_data)} | Çalışan: {successful}\n"
    m3u_content += f"# https://github.com/Tahir2020/TR_Avrupa\n\n"
    
    for group_name, channels in sorted(groups.items()):
        working = sum(1 for ch in channels if ch.get('stream_url'))
        m3u_content += f"\n# === {group_name.upper()} ({working}/{len(channels)}) ===\n"
        for ch in channels:
            if ch.get('stream_url'):
                m3u_content += f'#EXTINF:-1 tvg-name="{ch["channel_name"]}" tvg-logo="{ch["channel_logo"]}" group-title="{ch["group_title"]}", {ch["channel_name"]}\n'
                m3u_content += f'{ch["stream_url"]}\n'
            else:
                m3u_content += f'#EXTINF:-1 group-title="{ch["group_title"]}", ⚠️ {ch["channel_name"]}\n'
                m3u_content += f'# OFFLINE\n'
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(m3u_content)
    
    return successful


def process_channel(channel: Dict, quality: str, method: str = 'python') -> Dict:
    name = channel['channel_name'][:25]
    print(f"🔄 {name:25} | {channel['group_title']:12}", end=" ", flush=True)
    
    if method == 'python':
        stream_url = get_stream_url(channel['youtube_url'], quality)
    else:
        stream_url = get_stream_url_subprocess(channel['youtube_url'], quality)
    
    result = channel.copy()
    result['stream_url'] = stream_url
    
    if stream_url:
        if save_channel_m3u(channel, stream_url):
            print("✅")
        else:
            print("⚠️")
    else:
        print("")  # Hata zaten print edildi
    
    return result


def main():
    print("=" * 70)
    print("🎬 TÜRKİYE IPTV - 23 KANAL YAYIN GÜNCELLEYİCİ")
    print("=" * 70)
    
    config = load_config()
    channels = config['channels']
    quality = config['quality']
    
    # Cookie kontrolü
    cookie_valid = check_cookie_file()
    
    print(f"\n📡 Toplam kanal: {len(channels)}")
    print(f"🎯 Kalite: {quality}")
    print(f"🍪 Cookies: {'✅ Geçerli' if cookie_valid else '❌ Yok/Geçersiz'}")
    
    # Yöntem seçimi
    use_python_module = True
    
    try:
        import yt_dlp
        print(f"📦 yt-dlp module: ✅ {yt_dlp.__version__}")
    except ImportError:
        use_python_module = False
        print(f"📦 yt-dlp module: ❌ (subprocess kullanılacak)")
    
    print(f"🚀 Başlıyor...\n")
    
    if not cookie_valid:
        print("⚠️ UYARI: Geçerli cookies.txt bulunamadı!")
        print("💡 YouTube artık oturum gerektiriyor.")
        print("💡 Aşağıdaki adımları izleyin:\n")
        print("   1. Chrome'a 'Get cookies.txt' extension yükleyin")
        print("   2. YouTube'da oturum açın")
        print("   3. Extension ile cookies.txt export edin")
        print("   4. Dosyayı repo'ya koyun\n")
    
    start_time = datetime.now()
    processed = []
    
    method = 'python' if use_python_module else 'subprocess'
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(process_channel, ch, quality, method): ch for ch in channels}
        for future in as_completed(futures):
            try:
                processed.append(future.result())
            except Exception as e:
                ch = futures[future]
                print(f"❌ {ch['channel_name']}: {e}")
                ch_copy = ch.copy()
                ch_copy['stream_url'] = None
                processed.append(ch_copy)
    
    successful = save_master_playlist(processed, 'playerlist.m3u')
    
    elapsed = (datetime.now() - start_time).total_seconds()
    
    print("\n" + "=" * 70)
    print("📊 TARAMA RAPORU")
    print("=" * 70)
    print(f"✅ Başarılı: {successful}/{len(processed)} kanal")
    print(f"⏱️  Süre: {elapsed:.1f} saniye")
    print(f"📁 Master playlist: playerlist.m3u")
    
    # Grup bazlı
    print("\n📺 GRUP BAZLI DURUM:")
    groups = {}
    for ch in processed:
        g = ch['group_title']
        if g not in groups:
            groups[g] = {'total': 0, 'ok': 0}
        groups[g]['total'] += 1
        if ch['stream_url']:
            groups[g]['ok'] += 1
    
    for g, stats in sorted(groups.items()):
        icon = "✅" if stats['ok'] == stats['total'] else "⚠️" if stats['ok'] > 0 else "❌"
        print(f"   {icon} {g:15}: {stats['ok']:2}/{stats['total']}")
    
    if successful > 0:
        print(f"\n🎉 {successful} kanal başarıyla güncellendi!")
        sys.exit(0)
    else:
        print("\n⚠️ Hiçbir kanal çalışmıyor!")
        print("\nÇÖZÜM:")
        print("1. YouTube'da oturum açtığınızdan emin olun")
        print("2. 'Get cookies.txt' extension ile yeni cookies alın")
        print("3. cookies.txt'yi base64'e çevirip GitHub Secret'a ekleyin")
        sys.exit(1)


if __name__ == "__main__":
    main()
