"""MCP server untuk MetaTrader 5."""

from __future__ import annotations

import argparse
from typing import Any

from mcp.types import ToolAnnotations

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore[no-redef]

from . import indicators as ind
from .config import Settings
from .mt5_client import TIMEFRAMES, MT5Client, MT5Error

READ = ToolAnnotations.model_validate({"readOnlyHint": True, "openWorldHint": True})
WRITE = ToolAnnotations.model_validate(
    {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True}
)

INSTRUCTIONS = """\
Server ini terhubung ke terminal MetaTrader 5 milik pengguna.
- Gunakan tool read-only (account_info, get_tick, get_rates, get_indicators, get_positions,
  get_history, calculate_lot_size) secara bebas.
- Sebelum place_order / close_position / modify_position / cancel_order, SELALU tampilkan
  detail order (simbol, arah, lot, SL, TP) ke pengguna dan minta konfirmasi eksplisit.
- Gunakan dry_run=true untuk memeriksa margin & validitas order tanpa mengeksekusi.
- Waktu yang dikembalikan adalah waktu server broker.
"""


def build_server(client: MT5Client | None = None) -> Any:
    client = client or MT5Client(Settings.from_env())
    server = _Server(name="mt5-trading", instructions=INSTRUCTIONS)

    # ---------------------------------------------------------------- read
    @server.tool(annotations=READ)
    def account_info() -> dict[str, Any]:
        """Info akun MT5: balance, equity, margin, leverage, mode (DEMO/REAL)."""
        return client.account_info()

    @server.tool(annotations=READ)
    def terminal_status() -> dict[str, Any]:
        """Status terminal MT5: terhubung ke broker, AutoTrading diizinkan, ping."""
        return client.terminal_status()

    @server.tool(annotations=READ)
    def search_symbols(query: str, limit: int = 50) -> list[str]:
        """Cari nama simbol di broker, mis. 'XAU' -> ['XAUUSD', 'XAUUSDm']."""
        return client.search_symbols(query, limit)

    @server.tool(annotations=READ)
    def symbol_info(symbol: str) -> dict[str, Any]:
        """Spesifikasi simbol: digits, point, spread, lot min/max/step, tick value, stops level."""
        return client.symbol_info(symbol)

    @server.tool(annotations=READ)
    def get_tick(symbol: str) -> dict[str, Any]:
        """Harga bid/ask terakhir dan spread (point) untuk simbol."""
        return client.tick(symbol)

    @server.tool(annotations=READ)
    def get_rates(symbol: str, timeframe: str = "H1", count: int = 100) -> list[dict[str, Any]]:
        """Candle OHLC terakhir. timeframe: M1,M5,M15,M30,H1,H4,D1,W1,MN1 dll. count maks 5000."""
        return client.rates(symbol, timeframe, count)

    @server.tool(annotations=READ)
    def get_indicators(
        symbol: str,
        timeframe: str = "H1",
        sma_period: int = 50,
        ema_period: int = 20,
        rsi_period: int = 14,
        atr_period: int = 14,
    ) -> dict[str, Any]:
        """Hitung SMA, EMA, RSI, ATR dari candle tertutup terakhir, plus ringkasan trend."""
        need = max(sma_period, ema_period * 3, rsi_period * 10, atr_period * 10, 50)
        bars = client.rates(symbol, timeframe, need + 1)[:-1]  # buang candle berjalan
        closes = [b["close"] for b in bars]
        highs = [b["high"] for b in bars]
        lows = [b["low"] for b in bars]
        last = closes[-1] if closes else None
        sma_v = ind.sma(closes, sma_period)
        ema_v = ind.ema(closes, ema_period)
        rsi_v = ind.rsi(closes, rsi_period)
        atr_v = ind.atr(highs, lows, closes, atr_period)
        trend = None
        if last is not None and sma_v is not None and ema_v is not None:
            if last > ema_v > sma_v:
                trend = "BULLISH"
            elif last < ema_v < sma_v:
                trend = "BEARISH"
            else:
                trend = "SIDEWAYS/MIXED"
        r = lambda v: None if v is None else round(v, 5)  # noqa: E731
        return {
            "symbol": symbol,
            "timeframe": timeframe.upper(),
            "last_closed_bar": bars[-1]["time"] if bars else None,
            "close": last,
            f"sma_{sma_period}": r(sma_v),
            f"ema_{ema_period}": r(ema_v),
            f"rsi_{rsi_period}": None if rsi_v is None else round(rsi_v, 2),
            f"atr_{atr_period}": r(atr_v),
            "trend": trend,
            "bars_used": len(bars),
        }

    @server.tool(annotations=READ)
    def get_positions(symbol: str | None = None) -> list[dict[str, Any]]:
        """Daftar posisi terbuka (opsional filter simbol)."""
        return client.positions(symbol)

    @server.tool(annotations=READ)
    def get_pending_orders(symbol: str | None = None) -> list[dict[str, Any]]:
        """Daftar pending order (limit/stop) yang aktif."""
        return client.pending_orders(symbol)

    @server.tool(annotations=READ)
    def get_history(days: int = 7, symbol: str | None = None) -> dict[str, Any]:
        """Riwayat deal N hari terakhir + ringkasan win rate & net profit."""
        return client.history_deals(days, symbol)

    @server.tool(annotations=READ)
    def calculate_lot_size(symbol: str, risk_percent: float, sl_points: float) -> dict[str, Any]:
        """Hitung lot berdasarkan % risiko dari balance dan jarak SL dalam point.

        Contoh XAUUSD 2 digit: SL $5 = 500 point.
        """
        max_risk = client.settings.max_risk_percent
        if risk_percent > max_risk:
            raise MT5Error(f"risk_percent {risk_percent} melebihi MT5_MAX_RISK_PERCENT={max_risk}.")
        return client.calculate_lot(symbol, risk_percent, sl_points)

    # --------------------------------------------------------------- write
    @server.tool(annotations=WRITE)
    def place_order(
        symbol: str,
        side: str,
        volume: float,
        order_type: str = "MARKET",
        price: float | None = None,
        sl: float | None = None,
        tp: float | None = None,
        comment: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Kirim order. side=BUY|SELL, order_type=MARKET|LIMIT|STOP (price wajib utk LIMIT/STOP).

        sl/tp dalam harga absolut. dry_run=true hanya memeriksa (order_check) tanpa eksekusi.
        Minta konfirmasi pengguna sebelum eksekusi nyata.
        """
        return client.place_order(symbol, side, volume, order_type, price, sl, tp, comment, dry_run)

    @server.tool(annotations=WRITE)
    def close_position(ticket: int, volume: float | None = None, dry_run: bool = False) -> dict[str, Any]:
        """Tutup posisi berdasarkan ticket (penuh, atau sebagian dengan volume)."""
        return client.close_position(ticket, volume, dry_run)

    @server.tool(annotations=WRITE)
    def modify_position(ticket: int, sl: float | None = None, tp: float | None = None) -> dict[str, Any]:
        """Ubah SL dan/atau TP posisi terbuka (harga absolut)."""
        return client.modify_position(ticket, sl, tp)

    @server.tool(annotations=WRITE)
    def cancel_order(ticket: int) -> dict[str, Any]:
        """Batalkan pending order berdasarkan ticket."""
        return client.cancel_order(ticket)

    @server.resource("mt5://timeframes")
    def timeframes() -> str:
        """Daftar timeframe yang didukung."""
        return ", ".join(TIMEFRAMES)

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="MCP server MetaTrader 5")
    parser.add_argument(
        "--transport", choices=["stdio", "streamable-http", "sse"], default="stdio"
    )
    args = parser.parse_args()
    build_server().run(transport=args.transport)


if __name__ == "__main__":
    main()
