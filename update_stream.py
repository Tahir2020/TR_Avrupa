#!/bin/bash

# ============================================
# TV KANALLARI M3U8 GÜNCELLEYICI (HLS FORMATINDA)
# ============================================

CONFIG_FILE="config.json"
OUTPUT_DIR="playlist"
MAIN_PLAYLIST="playlist.m3u8"
COOKIE_FILE="cookies.txt"

CHROME_UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/148.0.0.0 Safari/537.36"

# Renkli çıktı için
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============================================
# FONKSIYONLAR
# ============================================

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

# YouTube'dan HLS manifest URL'sini çek
get_youtube_hls_url() {
    local youtube_url="$1"
    local quality="${2:-best[height<=1080][fps<=50]/best}"
    
    # yt-dlp ile m3u8 URL'sini al
    local manifest_url=$(yt-dlp -g --cookies "$COOKIE_FILE" \
        --js-runtimes "deno" \
        --remote-components "ejs:github" \
        --extractor-args "youtube:player_client=android" \
        -f "$quality" \
        "$youtube_url" 2>/dev/null | grep -i "manifest.googlevideo.com" | head -n 1 | tr -d '\r\n')
    
    if [[ -n "$manifest_url" ]]; then
        echo "$manifest_url"
        return 0
    fi
    
    # İkinci deneme: farklı format
    manifest_url=$(yt-dlp -g --cookies "$COOKIE_FILE" \
        --extractor-args "youtube:player_client=default" \
        -f "best[ext=m3u8]" \
        "$youtube_url" 2>/dev/null | head -n 1 | tr -d '\r\n')
    
    if [[ -n "$manifest_url" ]]; then
        echo "$manifest_url"
        return 0
    fi
    
    return 1
}

# Direkt m3u8 URL'sini kontrol et
is_direct_m3u8() {
    local url="$1"
    [[ "$url" =~ \.m3u8($|\?) ]]
}

# ATV Avrupa token al
get_atv_avrupa_token() {
    local token_url="https://securevideotoken.tmgrup.com.tr/webtv/secure?$(date +%s%3N)&url=https%3A%2F%2Ftrkvz-live.ercdn.net%2Fatvavrupa%2Fatvavrupa_576p.m3u8&url2=https%3A%2F%2Ftrkvz-live.ercdn.net%2Fatvavrupa%2Fatvavrupa_576p.m3u8"
    
    local token=$(curl -s --max-time 15 \
        -H "User-Agent: $CHROME_UA" \
        -H "X-isApp: 1" \
        -H "Referer: https://www.atvavrupa.tv/" \
        "$token_url" | jq -r '.Url // empty' 2>/dev/null)
    
    if [[ -n "$token" ]]; then
        echo "$token"
        return 0
    fi
    return 1
}

# EuroStar token al
get_eurostar_token() {
    local page_url="https://www.eurostartv.com.tr/canli-izle"
    
    local token=$(curl -s --max-time 15 \
        -H "User-Agent: $CHROME_UA" \
        "$page_url" | grep -oP "token=\K[a-f0-9]+" | head -n 1)
    
    if [[ -n "$token" ]]; then
        local token_url="https://dygvideo.dygdigital.com/live/hls/staravrupa?token=$token"
        local master_url=$(curl -s -I --max-time 10 \
            -H "User-Agent: $CHROME_UA" \
            -H "Origin: https://www.eurostartv.com.tr" \
            "$token_url" | grep -i "location:" | awk '{print $2}' | tr -d '\r')
        
        if [[ -n "$master_url" ]]; then
            # 1080p stream'e yönlendir
            local stream_url=$(echo "$master_url" | sed 's|/live\.m3u8|/live_1080p3000000kbps/index.m3u8|')
            echo "$stream_url"
            return 0
        fi
    fi
    return 1
}

# Show Türk token al
get_show_turk_token() {
    local page_url="https://www.showturk.com.tr/canli-yayin"
    
    local stream_url=$(curl -s --max-time 15 \
        -H "User-Agent: $CHROME_UA" \
        "$page_url" | grep -oP "playlist\.m3u8\?e=\d+&st=[^\"&]+" | head -n 1)
    
    if [[ -n "$stream_url" ]]; then
        echo "https://ciner-live.ercdn.net/showturk/$stream_url&tv=1"
        return 0
    fi
    return 1
}

# Kanal URL'sini bul
get_stream_url() {
    local name="$1"
    local url="$2"
    local quality="$3"
    
    # ATV Avrupa kontrolü
    if [[ "$name" =~ [Aa][Tt][Vv] && "$name" =~ [Aa]vrupa ]]; then
        log_info "ATV Avrupa token alınıyor..."
        get_atv_avrupa_token
        return $?
    fi
    
    # EuroStar kontrolü
    if [[ "$name" =~ [Ee]uro[[:space:]]*[Ss]tar || "$name" =~ [Ss]tar[[:space:]]*[Aa]vrupa ]]; then
        log_info "EuroStar token alınıyor..."
        get_eurostar_token
        return $?
    fi
    
    # Show Türk kontrolü
    if [[ "$name" =~ [Ss]how[[:space:]]*[Tt]ürk ]]; then
        log_info "Show Türk token alınıyor..."
        get_show_turk_token
        return $?
    fi
    
    # Direkt m3u8 kontrolü
    if is_direct_m3u8 "$url"; then
        echo "$url"
        return 0
    fi
    
    # YouTube kontrolü
    if [[ "$url" =~ youtube\.com || "$url" =~ youtu\.be ]]; then
        log_info "YouTube stream alınıyor..."
        get_youtube_hls_url "$url" "$quality"
        return $?
    fi
    
    # Varsayılan
    echo "$url"
    return 0
}

# HLS playlist oluştur (sade ve temiz)
create_hls_playlist() {
    local stream_url="$1"
    
    cat <<EOF
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-STREAM-INF:BANDWIDTH=1280000,RESOLUTION=1280x720
$stream_url
EOF
}

# Ana playlist entry oluştur
create_main_entry() {
    local name="$1"
    local stream_url="$2"
    
    cat <<EOF
#EXTINF:-1,$name
$stream_url
EOF
}

# ============================================
# ANA PROGRAM
# ============================================

main() {
    echo "============================================================"
    echo "   TV KANALLARI M3U8 GÜNCELLEYICI (HLS FORMATINDA)"
    echo "============================================================"
    echo "Baslangic: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "============================================================"
    
    # Config kontrol
    if [[ ! -f "$CONFIG_FILE" ]]; then
        log_error "$CONFIG_FILE bulunamadı!"
        exit 1
    fi
    
    # Çıktı klasörünü oluştur
    mkdir -p "$OUTPUT_DIR"
    
    # Kanal listesini oku
    local channels=$(jq -c '.channels[]' "$CONFIG_FILE" 2>/dev/null)
    local total=$(echo "$channels" | wc -l)
    local quality=$(jq -r '.quality // "best[height<=1080][fps<=50]/best"' "$CONFIG_FILE")
    
    # Eski dosyaları temizle (playerlist hariç)
    find "$OUTPUT_DIR" -name "*.m3u8" ! -name "playerlist.m3u8" -delete 2>/dev/null
    find "$OUTPUT_DIR" -name "*.m3u" ! -name "playerlist.m3u" -delete 2>/dev/null
    
    local main_entries=""
    local success_count=0
    local fail_count=0
    local failed_list=""
    
    local index=0
    while IFS= read -r channel; do
        index=$((index + 1))
        
        local name=$(echo "$channel" | jq -r '.name')
        local url=$(echo "$channel" | jq -r '.url // .youtube_url // empty')
        
        if [[ -z "$url" ]]; then
            log_warning "[$index/$total] $name: URL yok, atlaniyor"
            fail_count=$((fail_count + 1))
            failed_list="${failed_list}\n   - $name"
            continue
        fi
        
        echo ""
        log_info "[$index/$total] $name taranıyor..."
        echo "----------------------------------------"
        
        # Stream URL'sini al
        local stream_url=$(get_stream_url "$name" "$url" "$quality")
        
        if [[ -z "$stream_url" ]]; then
            log_error "$name: Stream URL alınamadı"
            fail_count=$((fail_count + 1))
            failed_list="${failed_list}\n   - $name"
            continue
        fi
        
        # Güvenli dosya adı oluştur
        local safe_name=$(echo "$name" | sed 's/ç/c/g; s/ğ/g/g; s/ı/i/g; s/ö/o/g; s/ş/s/g; s/ü/u/g; s/Ç/C/g; s/Ğ/G/g; s/İ/I/g; s/Ö/O/g; s/Ş/S/g; s/Ü/U/g' | sed 's/[^A-Za-z0-9._-]/_/g')
        local filename="${safe_name}.m3u8"
        local filepath="$OUTPUT_DIR/$filename"
        
        # HLS playlist oluştur (sade ve temiz)
        create_hls_playlist "$stream_url" > "$filepath"
        
        # Ana playlist için entry ekle
        main_entries="${main_entries}$(create_main_entry "$name" "$stream_url")\n"
        
        log_success "$name: $filename oluşturuldu"
        success_count=$((success_count + 1))
        
        # Rate limiting
        sleep 0.5
        
    done <<< "$channels"
    
    # Ana playlist'i oluştur
    if [[ -n "$main_entries" ]]; then
        cat <<EOF > "$OUTPUT_DIR/$MAIN_PLAYLIST"
#EXTM3U
#EXT-X-VERSION:3
$main_entries
EOF
        log_success "Toplu liste oluşturuldu: $OUTPUT_DIR/$MAIN_PLAYLIST"
        
        # Uyumluluk dosyaları
        cp "$OUTPUT_DIR/$MAIN_PLAYLIST" "$OUTPUT_DIR/playerlist.m3u" 2>/dev/null
        cp "$OUTPUT_DIR/$MAIN_PLAYLIST" "$OUTPUT_DIR/playerlist.m3u8" 2>/dev/null
    fi
    
    # Özet
    echo ""
    echo "============================================================"
    echo "SONUÇ: $success_count/$total kanal başarılı"
    
    if [[ $fail_count -gt 0 ]]; then
        echo -e "Başarısız kanallar:$failed_list"
    fi
    
    echo ""
    echo "Oluşturulan dosyalar ($OUTPUT_DIR/):"
    ls -la "$OUTPUT_DIR"/*.m3u8 2>/dev/null | awk '{print "   - " $9}' | sed 's|.*/||'
    
    echo ""
    echo "Örnek dosya içeriği ($(ls "$OUTPUT_DIR"/*.m3u8 2>/dev/null | head -n 1 | sed 's|.*/||')):"
    echo "----------------------------------------"
    head -5 "$OUTPUT_DIR"/*.m3u8 2>/dev/null | head -10
    
    echo ""
    echo "============================================================"
    echo "Bitiş: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "============================================================"
    
    if [[ $success_count -eq 0 ]]; then
        exit 1
    fi
    return 0
}

# Çalıştır
main
exit $?
