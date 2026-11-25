# mt5-trading-mcp

MCP server (Python) yang menghubungkan Claude ke terminal **MetaTrader 5**: harga live,
candle, indikator, posisi, riwayat, kalkulator lot, dan eksekusi order dengan pengaman.

> ⚠️ Paket `MetaTrader5` hanya berjalan di **Windows** dengan terminal MT5 terpasang dan
> login. Jalankan server ini di komputer/VPS Windows yang sama dengan terminal MT5.

## Tools

| Tool | Jenis | Fungsi |
|---|---|---|
| `account_info` | baca | Balance, equity, margin, leverage, mode DEMO/REAL |
| `terminal_status` | baca | Koneksi broker, AutoTrading, ping |
| `search_symbols` | baca | Cari nama simbol (mis. `XAU` → `XAUUSD`, `XAUUSDm`) |
| `symbol_info` | baca | Digits, point, spread, lot min/max/step, tick value, stops level |
| `get_tick` | baca | Bid/ask terakhir + spread |
| `get_rates` | baca | Candle OHLC (M1…MN1, maks 5000) |
| `get_indicators` | baca | SMA, EMA, RSI, ATR + ringkasan trend (candle tertutup) |
| `get_positions` / `get_pending_orders` | baca | Posisi & pending order aktif |
| `get_history` | baca | Deal N hari terakhir + win rate & net profit |
| `calculate_lot_size` | baca | Lot dari % risiko & jarak SL (point) |
| `place_order` | **tulis** | MARKET / LIMIT / STOP, SL/TP, `dry_run` |
| `close_position` | **tulis** | Tutup penuh atau sebagian |
| `modify_position` | **tulis** | Ubah SL/TP |
| `cancel_order` | **tulis** | Batalkan pending order |

## Pengaman eksekusi

Secara default server **read-only**. Semua tool tulis ditolak kecuali:

| Variabel | Default | Arti |
|---|---|---|
| `MT5_TRADING_ENABLED` | `false` | Harus `true` agar order bisa dieksekusi |
| `MT5_ALLOW_REAL_ACCOUNT` | `false` | Akun REAL diblokir kecuali `true` (DEMO selalu boleh) |
| `MT5_MAX_LOT` | `1.0` | Lot maksimum per order |
| `MT5_MAX_RISK_PERCENT` | `2.0` | Batas `risk_percent` di kalkulator lot |
| `MT5_SYMBOL_WHITELIST` | (kosong = semua) | Mis. `XAUUSD,EURUSD` |

Validasi tambahan: volume dibulatkan ke `volume_step`, SL/TP harus di sisi yang benar dan
memenuhi `trade_stops_level`. `dry_run=true` memakai `order_check` (cek margin) tanpa
mengirim order — bisa dipakai walau trading dinonaktifkan.

Variabel lain: `MT5_PATH` (path `terminal64.exe`), `MT5_LOGIN`, `MT5_PASSWORD`,
`MT5_SERVER` (kosongkan untuk memakai akun yang sedang login di terminal),
`MT5_MAGIC` (default `20260204`), `MT5_DEVIATION` (default `20`), `MT5_COMMENT`.

## Instalasi (Windows)

```powershell
cd agus\mcp-server-trading
python -m venv .venv
.venv\Scripts\pip install -e .
```

Pastikan terminal MT5 terbuka, sudah login, dan tombol **Algo Trading** aktif.

## Pasang di Claude Desktop / Claude Code

`claude_desktop_config.json` (salinan siap pakai: [`claude_desktop_config.example.json`](claude_desktop_config.example.json) — ganti `C:\path\ke\...` dengan path folder Anda):

```json
{
  "mcpServers": {
    "mt5-trading": {
      "command": "C:\\path\\ke\\agus\\mcp-server-trading\\.venv\\Scripts\\mt5-trading-mcp.exe",
      "env": {
        "MT5_TRADING_ENABLED": "false",
        "MT5_MAX_LOT": "0.5",
        "MT5_SYMBOL_WHITELIST": "XAUUSD"
      }
    }
  }
}
```

Claude Code:

```powershell
claude mcp add mt5-trading -e MT5_TRADING_ENABLED=false -- C:\path\ke\.venv\Scripts\mt5-trading-mcp.exe
```

Transport HTTP (mis. dari VPS): `mt5-trading-mcp --transport streamable-http`.

## Contoh prompt

- "Cek akun MT5 saya dan posisi XAUUSD yang terbuka."
- "Tampilkan RSI, ATR dan trend XAUUSD H1 dan H4."
- "Risiko 1%, SL 500 point di XAUUSD — berapa lot?"
- "Dry run BUY XAUUSD 0.2 lot SL 2640 TP 2680."

## Pengembangan & tes (bisa di Linux/macOS)

Tes memakai modul MT5 palsu (`tests/fake_mt5.py`), jadi tidak butuh terminal:

```bash
pip install -e ".[dev]"
pytest
```

*Bukan saran finansial. Uji di akun DEMO dulu.*
