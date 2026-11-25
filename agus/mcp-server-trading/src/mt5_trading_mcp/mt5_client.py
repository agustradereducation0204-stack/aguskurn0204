"""Pembungkus thread-safe untuk paket Python `MetaTrader5`.

Paket `MetaTrader5` hanya tersedia di Windows dan butuh terminal MT5 yang
terpasang. Modul ini diimpor secara lazy dan bisa diganti (dependency
injection) agar bisa diuji di Linux dengan modul palsu.
"""

from __future__ import annotations

import math
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import Settings

try:  # mcp >= 2
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp.exceptions import ToolError  # type: ignore[no-redef]

TIMEFRAMES = (
    "M1", "M2", "M3", "M4", "M5", "M6", "M10", "M12", "M15", "M20", "M30",
    "H1", "H2", "H3", "H4", "H6", "H8", "H12", "D1", "W1", "MN1",
)

PENDING_TYPES = ("BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP")

ACCOUNT_MODES = {0: "DEMO", 1: "CONTEST", 2: "REAL"}


class MT5Error(ToolError):
    """Kesalahan dari terminal MT5 atau dari aturan pengaman server.

    Turunan ToolError agar pesannya diteruskan ke klien MCP (bukan disamarkan).
    """


def _load_mt5() -> Any:
    try:
        import MetaTrader5 as mt5  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - tergantung platform
        raise MT5Error(
            "Paket 'MetaTrader5' tidak terpasang. Jalankan server ini di Windows "
            "dengan terminal MT5 terpasang lalu `pip install MetaTrader5`."
        ) from exc
    return mt5


def _ts(epoch: int | float) -> str:
    """Epoch MT5 (waktu server broker, diperlakukan sbg UTC) -> ISO string."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _asdict(obj: Any) -> dict[str, Any]:
    return dict(obj._asdict()) if hasattr(obj, "_asdict") else dict(vars(obj))


class MT5Client:
    def __init__(self, settings: Settings, mt5_module: Any | None = None) -> None:
        self.settings = settings
        self._mt5 = mt5_module
        self._lock = threading.RLock()
        self._connected = False

    # ------------------------------------------------------------------ koneksi
    @property
    def mt5(self) -> Any:
        if self._mt5 is None:
            self._mt5 = _load_mt5()
        return self._mt5

    def _error(self, what: str) -> MT5Error:
        code, msg = self.mt5.last_error()
        return MT5Error(f"{what} gagal: [{code}] {msg}")

    def ensure_connected(self) -> None:
        with self._lock:
            if self._connected and self.mt5.terminal_info() is not None:
                return
            s = self.settings
            kwargs: dict[str, Any] = {"timeout": s.timeout_ms}
            if s.login is not None:
                kwargs.update(login=s.login, password=s.password or "", server=s.server or "")
            args = (s.terminal_path,) if s.terminal_path else ()
            if not self.mt5.initialize(*args, **kwargs):
                raise self._error("initialize()")
            self._connected = True

    def shutdown(self) -> None:
        with self._lock:
            if self._connected and self._mt5 is not None:
                self._mt5.shutdown()
            self._connected = False

    # --------------------------------------------------------------- utilitas
    def _symbol_info(self, symbol: str) -> Any:
        mt5 = self.mt5
        info = mt5.symbol_info(symbol)
        if info is None:
            raise MT5Error(f"Simbol '{symbol}' tidak ditemukan di broker ini.")
        if not info.visible and not mt5.symbol_select(symbol, True):
            raise self._error(f"symbol_select({symbol})")
        return info

    def _timeframe(self, timeframe: str) -> int:
        tf = timeframe.upper()
        if tf not in TIMEFRAMES:
            raise MT5Error(f"Timeframe '{timeframe}' tidak valid. Pilihan: {', '.join(TIMEFRAMES)}")
        return getattr(self.mt5, f"TIMEFRAME_{tf}")

    @staticmethod
    def _round_volume(volume: float, info: Any) -> float:
        step = info.volume_step or 0.01
        lots = math.floor(volume / step + 1e-9) * step
        decimals = max(0, -int(math.floor(math.log10(step)))) if step < 1 else 0
        return round(lots, decimals)

    def _filling_mode(self, info: Any) -> int:
        mt5 = self.mt5
        mode = int(getattr(info, "filling_mode", 0))
        if mode & 1:  # SYMBOL_FILLING_FOK
            return mt5.ORDER_FILLING_FOK
        if mode & 2:  # SYMBOL_FILLING_IOC
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    # ------------------------------------------------------------- read-only
    def account_info(self) -> dict[str, Any]:
        with self._lock:
            self.ensure_connected()
            info = self.mt5.account_info()
            if info is None:
                raise self._error("account_info()")
            d = _asdict(info)
            keys = (
                "login", "name", "server", "currency", "leverage", "balance", "equity",
                "margin", "margin_free", "margin_level", "profit", "company",
            )
            out = {k: d.get(k) for k in keys}
            out["mode"] = ACCOUNT_MODES.get(d.get("trade_mode"), str(d.get("trade_mode")))
            out["trade_allowed"] = d.get("trade_allowed")
            return out

    def terminal_status(self) -> dict[str, Any]:
        with self._lock:
            self.ensure_connected()
            t = _asdict(self.mt5.terminal_info())
            return {
                "connected": t.get("connected"),
                "trade_allowed": t.get("trade_allowed"),
                "company": t.get("company"),
                "name": t.get("name"),
                "build": t.get("build"),
                "ping_ms": round(t.get("ping_last", 0) / 1000, 1),
            }

    def symbol_info(self, symbol: str) -> dict[str, Any]:
        with self._lock:
            self.ensure_connected()
            info = _asdict(self._symbol_info(symbol))
            keys = (
                "name", "description", "digits", "point", "spread", "trade_stops_level",
                "volume_min", "volume_max", "volume_step", "trade_contract_size",
                "trade_tick_value", "trade_tick_size", "currency_base", "currency_profit",
                "bid", "ask", "swap_long", "swap_short",
            )
            return {k: info.get(k) for k in keys}

    def search_symbols(self, query: str, limit: int = 50) -> list[str]:
        with self._lock:
            self.ensure_connected()
            group = query if any(c in query for c in "*,!") else f"*{query}*"
            symbols = self.mt5.symbols_get(group=group) or ()
            return [s.name for s in symbols][:limit]

    def tick(self, symbol: str) -> dict[str, Any]:
        with self._lock:
            self.ensure_connected()
            info = self._symbol_info(symbol)
            t = self.mt5.symbol_info_tick(symbol)
            if t is None:
                raise self._error(f"symbol_info_tick({symbol})")
            spread_points = round((t.ask - t.bid) / info.point) if info.point else None
            return {
                "symbol": symbol,
                "time": _ts(t.time),
                "bid": t.bid,
                "ask": t.ask,
                "last": t.last,
                "spread_points": spread_points,
            }

    def rates(self, symbol: str, timeframe: str = "H1", count: int = 100) -> list[dict[str, Any]]:
        count = max(1, min(int(count), 5000))
        with self._lock:
            self.ensure_connected()
            self._symbol_info(symbol)
            raw = self.mt5.copy_rates_from_pos(symbol, self._timeframe(timeframe), 0, count)
            if raw is None:
                raise self._error(f"copy_rates_from_pos({symbol}, {timeframe})")
            return [
                {
                    "time": _ts(int(r["time"])),
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                    "tick_volume": int(r["tick_volume"]),
                    "spread": int(r["spread"]),
                }
                for r in raw
            ]

    def positions(self, symbol: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            self.ensure_connected()
            raw = self.mt5.positions_get(symbol=symbol) if symbol else self.mt5.positions_get()
            if raw is None:
                raise self._error("positions_get()")
            return [self._fmt_position(p) for p in raw]

    def _fmt_position(self, p: Any) -> dict[str, Any]:
        return {
            "ticket": p.ticket,
            "symbol": p.symbol,
            "type": "BUY" if p.type == self.mt5.POSITION_TYPE_BUY else "SELL",
            "volume": p.volume,
            "price_open": p.price_open,
            "price_current": p.price_current,
            "sl": p.sl,
            "tp": p.tp,
            "profit": p.profit,
            "swap": p.swap,
            "magic": p.magic,
            "comment": p.comment,
            "time": _ts(p.time),
        }

    def pending_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            self.ensure_connected()
            raw = self.mt5.orders_get(symbol=symbol) if symbol else self.mt5.orders_get()
            if raw is None:
                raise self._error("orders_get()")
            names = {getattr(self.mt5, f"ORDER_TYPE_{n}"): n for n in PENDING_TYPES}
            return [
                {
                    "ticket": o.ticket,
                    "symbol": o.symbol,
                    "type": names.get(o.type, str(o.type)),
                    "volume": o.volume_current,
                    "price_open": o.price_open,
                    "sl": o.sl,
                    "tp": o.tp,
                    "magic": o.magic,
                    "comment": o.comment,
                    "time_setup": _ts(o.time_setup),
                }
                for o in raw
            ]

    def history_deals(self, days: int = 7, symbol: str | None = None) -> dict[str, Any]:
        days = max(1, min(int(days), 365))
        with self._lock:
            self.ensure_connected()
            # +1 hari untuk menutupi selisih zona waktu server broker.
            date_to = datetime.now() + timedelta(days=1)
            date_from = date_to - timedelta(days=days + 1)
            raw = self.mt5.history_deals_get(date_from, date_to)
            if raw is None:
                raise self._error("history_deals_get()")
            deals = []
            for d in raw:
                if symbol and d.symbol != symbol:
                    continue
                if not d.symbol:  # deposit / withdrawal / balance
                    continue
                deals.append(
                    {
                        "ticket": d.ticket,
                        "position_id": d.position_id,
                        "symbol": d.symbol,
                        "type": "BUY" if d.type == self.mt5.DEAL_TYPE_BUY else "SELL",
                        "entry": {0: "IN", 1: "OUT", 2: "INOUT", 3: "OUT_BY"}.get(d.entry, d.entry),
                        "volume": d.volume,
                        "price": d.price,
                        "profit": d.profit,
                        "commission": d.commission,
                        "swap": d.swap,
                        "magic": d.magic,
                        "comment": d.comment,
                        "time": _ts(d.time),
                    }
                )
            closed = [d for d in deals if d["entry"] in ("OUT", "OUT_BY", "INOUT")]
            net = sum(d["profit"] + d["commission"] + d["swap"] for d in deals)
            wins = sum(1 for d in closed if d["profit"] > 0)
            return {
                "deals": deals,
                "summary": {
                    "closed_trades": len(closed),
                    "wins": wins,
                    "losses": len(closed) - wins,
                    "win_rate_percent": round(100 * wins / len(closed), 1) if closed else None,
                    "net_profit": round(net, 2),
                },
            }

    def calculate_lot(self, symbol: str, risk_percent: float, sl_points: float) -> dict[str, Any]:
        if risk_percent <= 0 or sl_points <= 0:
            raise MT5Error("risk_percent dan sl_points harus > 0.")
        with self._lock:
            self.ensure_connected()
            info = self._symbol_info(symbol)
            acc = self.mt5.account_info()
            if acc is None:
                raise self._error("account_info()")
            risk_money = acc.balance * risk_percent / 100
            sl_price_distance = sl_points * info.point
            loss_per_lot = sl_price_distance / info.trade_tick_size * info.trade_tick_value
            if loss_per_lot <= 0:
                raise MT5Error("Tick value/size simbol tidak valid; tidak bisa menghitung lot.")
            raw_lots = risk_money / loss_per_lot
            lots = self._round_volume(raw_lots, info)
            note = None
            if lots < info.volume_min:
                note = (
                    f"Lot hasil hitung ({raw_lots:.4f}) di bawah minimum {info.volume_min}. "
                    "Perlebar risiko atau persempit SL."
                )
                lots = 0.0
            lots = min(lots, info.volume_max, self.settings.max_lot)
            return {
                "symbol": symbol,
                "balance": acc.balance,
                "currency": acc.currency,
                "risk_percent": risk_percent,
                "risk_money": round(risk_money, 2),
                "sl_points": sl_points,
                "loss_per_lot": round(loss_per_lot, 2),
                "lots": lots,
                "actual_risk_money": round(lots * loss_per_lot, 2),
                "note": note,
            }

    # ------------------------------------------------------------- eksekusi
    def _guard_trading(self, symbol: str, volume: float | None = None) -> None:
        s = self.settings
        if not s.trading_enabled:
            raise MT5Error(
                "Eksekusi order dinonaktifkan. Set MT5_TRADING_ENABLED=true untuk mengizinkan."
            )
        acc = self.mt5.account_info()
        if acc is None:
            raise self._error("account_info()")
        if acc.trade_mode == 2 and not s.allow_real_account:  # ACCOUNT_TRADE_MODE_REAL
            raise MT5Error(
                "Akun ini akun REAL. Eksekusi diblokir kecuali MT5_ALLOW_REAL_ACCOUNT=true."
            )
        if s.symbol_whitelist and symbol.upper() not in s.symbol_whitelist:
            raise MT5Error(f"Simbol '{symbol}' tidak ada di MT5_SYMBOL_WHITELIST.")
        if volume is not None and volume > s.max_lot:
            raise MT5Error(f"Volume {volume} melebihi batas MT5_MAX_LOT={s.max_lot}.")

    def _send(self, request: dict[str, Any], dry_run: bool) -> dict[str, Any]:
        mt5 = self.mt5
        if dry_run:
            res = mt5.order_check(request)
            if res is None:
                raise self._error("order_check()")
            d = _asdict(res)
            return {
                "dry_run": True,
                "ok": d.get("retcode") == 0,
                "retcode": d.get("retcode"),
                "comment": d.get("comment"),
                "margin": d.get("margin"),
                "margin_free_after": d.get("margin_free"),
                "request": request,
            }
        res = mt5.order_send(request)
        if res is None:
            raise self._error("order_send()")
        ok = res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED)
        return {
            "dry_run": False,
            "ok": ok,
            "retcode": res.retcode,
            "comment": res.comment,
            "order": res.order,
            "deal": res.deal,
            "volume": res.volume,
            "price": res.price,
            "request": request,
        }

    def place_order(
        self,
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
        side = side.upper()
        order_type = order_type.upper()
        if side not in ("BUY", "SELL"):
            raise MT5Error("side harus BUY atau SELL.")
        if order_type not in ("MARKET", "LIMIT", "STOP"):
            raise MT5Error("order_type harus MARKET, LIMIT, atau STOP.")
        with self._lock:
            self.ensure_connected()
            mt5 = self.mt5
            info = self._symbol_info(symbol)
            vol = self._round_volume(volume, info)
            if vol < info.volume_min or vol > info.volume_max:
                raise MT5Error(
                    f"Volume {volume} di luar batas simbol "
                    f"({info.volume_min}–{info.volume_max}, step {info.volume_step})."
                )
            if not dry_run:
                self._guard_trading(symbol, vol)
            elif vol > self.settings.max_lot:
                raise MT5Error(f"Volume {vol} melebihi batas MT5_MAX_LOT={self.settings.max_lot}.")

            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                raise self._error(f"symbol_info_tick({symbol})")

            request: dict[str, Any] = {
                "symbol": symbol,
                "volume": vol,
                "deviation": self.settings.deviation,
                "magic": self.settings.magic,
                "comment": (comment or self.settings.comment)[:31],
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": self._filling_mode(info),
            }
            if sl:
                request["sl"] = round(sl, info.digits)
            if tp:
                request["tp"] = round(tp, info.digits)

            if order_type == "MARKET":
                request["action"] = mt5.TRADE_ACTION_DEAL
                request["type"] = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
                request["price"] = tick.ask if side == "BUY" else tick.bid
            else:
                if price is None or price <= 0:
                    raise MT5Error("price wajib diisi untuk order LIMIT/STOP.")
                request["action"] = mt5.TRADE_ACTION_PENDING
                request["type"] = getattr(mt5, f"ORDER_TYPE_{side}_{order_type}")
                request["price"] = round(price, info.digits)
                request["type_filling"] = mt5.ORDER_FILLING_RETURN

            self._validate_stops(side, request, info)
            return self._send(request, dry_run)

    @staticmethod
    def _validate_stops(side: str, request: dict[str, Any], info: Any) -> None:
        price = request["price"]
        sl, tp = request.get("sl"), request.get("tp")
        if side == "BUY":
            if sl and sl >= price:
                raise MT5Error(f"SL BUY ({sl}) harus di bawah harga entry ({price}).")
            if tp and tp <= price:
                raise MT5Error(f"TP BUY ({tp}) harus di atas harga entry ({price}).")
        else:
            if sl and sl <= price:
                raise MT5Error(f"SL SELL ({sl}) harus di atas harga entry ({price}).")
            if tp and tp >= price:
                raise MT5Error(f"TP SELL ({tp}) harus di bawah harga entry ({price}).")
        min_dist = (info.trade_stops_level or 0) * info.point
        for name, level in (("SL", sl), ("TP", tp)):
            if level and min_dist and abs(price - level) < min_dist:
                raise MT5Error(
                    f"{name} terlalu dekat: jarak minimum {info.trade_stops_level} point."
                )

    def _get_position(self, ticket: int) -> Any:
        res = self.mt5.positions_get(ticket=ticket)
        if not res:
            raise MT5Error(f"Posisi dengan ticket {ticket} tidak ditemukan.")
        return res[0]

    def close_position(self, ticket: int, volume: float | None = None, dry_run: bool = False) -> dict[str, Any]:
        with self._lock:
            self.ensure_connected()
            mt5 = self.mt5
            pos = self._get_position(ticket)
            info = self._symbol_info(pos.symbol)
            if not dry_run:
                self._guard_trading(pos.symbol)
            vol = pos.volume if volume is None else self._round_volume(min(volume, pos.volume), info)
            if vol <= 0:
                raise MT5Error("Volume penutupan harus > 0.")
            tick = mt5.symbol_info_tick(pos.symbol)
            is_buy = pos.type == mt5.POSITION_TYPE_BUY
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": ticket,
                "symbol": pos.symbol,
                "volume": vol,
                "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
                "price": tick.bid if is_buy else tick.ask,
                "deviation": self.settings.deviation,
                "magic": pos.magic,
                "comment": "mcp close",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": self._filling_mode(info),
            }
            return self._send(request, dry_run)

    def modify_position(
        self, ticket: int, sl: float | None = None, tp: float | None = None
    ) -> dict[str, Any]:
        if sl is None and tp is None:
            raise MT5Error("Isi minimal salah satu dari sl atau tp.")
        with self._lock:
            self.ensure_connected()
            mt5 = self.mt5
            pos = self._get_position(ticket)
            info = self._symbol_info(pos.symbol)
            self._guard_trading(pos.symbol)
            new_sl = pos.sl if sl is None else round(sl, info.digits)
            new_tp = pos.tp if tp is None else round(tp, info.digits)
            side = "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"
            self._validate_stops(
                side, {"price": pos.price_current, "sl": new_sl, "tp": new_tp}, info
            )
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": ticket,
                "symbol": pos.symbol,
                "sl": new_sl,
                "tp": new_tp,
                "magic": pos.magic,
            }
            return self._send(request, dry_run=False)

    def cancel_order(self, ticket: int) -> dict[str, Any]:
        with self._lock:
            self.ensure_connected()
            mt5 = self.mt5
            orders = mt5.orders_get(ticket=ticket)
            if not orders:
                raise MT5Error(f"Pending order dengan ticket {ticket} tidak ditemukan.")
            self._guard_trading(orders[0].symbol)
            request = {"action": mt5.TRADE_ACTION_REMOVE, "order": ticket}
            return self._send(request, dry_run=False)
