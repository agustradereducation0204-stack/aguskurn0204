import asyncio
import json

import pytest

from fake_mt5 import FakeMT5
from mt5_trading_mcp import indicators as ind
from mt5_trading_mcp.config import Settings
from mt5_trading_mcp.mt5_client import MT5Client, MT5Error
from mt5_trading_mcp.server import build_server


def make_client(trade_mode=0, **settings):
    fake = FakeMT5(trade_mode=trade_mode)
    return MT5Client(Settings(**settings), mt5_module=fake), fake


# ------------------------------------------------------------- indikator
def test_indicators_basic():
    closes = [float(i) for i in range(1, 101)]
    assert ind.sma(closes, 10) == pytest.approx(95.5)
    assert ind.rsi(closes, 14) == 100.0
    assert ind.atr([c + 1 for c in closes], [c - 1 for c in closes], closes, 14) == pytest.approx(2.0)
    assert ind.sma(closes, 200) is None


# --------------------------------------------------------------- read-only
def test_account_and_tick():
    client, _ = make_client()
    acc = client.account_info()
    assert acc["mode"] == "DEMO" and acc["balance"] == 10_000.0
    t = client.tick("XAUUSD")
    assert t["spread_points"] == 20


def test_unknown_symbol():
    client, _ = make_client()
    with pytest.raises(MT5Error, match="tidak ditemukan"):
        client.tick("FOO")


def test_calculate_lot_xauusd():
    client, _ = make_client(max_lot=5.0)
    # 1% dari 10.000 = $100; SL 500 point ($5) -> rugi per lot $500 -> 0.2 lot
    res = client.calculate_lot("XAUUSD", 1.0, 500)
    assert res["lots"] == pytest.approx(0.2)
    assert res["actual_risk_money"] == pytest.approx(100.0)


# ---------------------------------------------------------------- pengaman
def test_trading_disabled_by_default():
    client, fake = make_client()
    with pytest.raises(MT5Error, match="MT5_TRADING_ENABLED"):
        client.place_order("XAUUSD", "BUY", 0.1, sl=2640, tp=2670)
    assert fake.sent == []


def test_real_account_blocked():
    client, fake = make_client(trade_mode=2, trading_enabled=True)
    with pytest.raises(MT5Error, match="REAL"):
        client.place_order("XAUUSD", "BUY", 0.1)
    assert fake.sent == []


def test_max_lot_and_whitelist():
    client, _ = make_client(trading_enabled=True, max_lot=0.5)
    with pytest.raises(MT5Error, match="MT5_MAX_LOT"):
        client.place_order("XAUUSD", "BUY", 1.0)
    client, _ = make_client(trading_enabled=True, symbol_whitelist=frozenset({"EURUSD"}))
    with pytest.raises(MT5Error, match="WHITELIST"):
        client.place_order("XAUUSD", "BUY", 0.1)


def test_dry_run_does_not_send_even_if_disabled():
    client, fake = make_client()
    res = client.place_order("XAUUSD", "SELL", 0.1, sl=2660, tp=2630, dry_run=True)
    assert res["dry_run"] and res["ok"]
    assert fake.sent == []


def test_invalid_stops():
    client, _ = make_client(trading_enabled=True)
    with pytest.raises(MT5Error, match="SL BUY"):
        client.place_order("XAUUSD", "BUY", 0.1, sl=2660)
    with pytest.raises(MT5Error, match="terlalu dekat"):
        client.place_order("XAUUSD", "BUY", 0.1, sl=2650.0)  # 20 point < stops level 50


# ---------------------------------------------------------------- eksekusi
def test_market_order_sent():
    client, fake = make_client(trading_enabled=True)
    res = client.place_order("XAUUSD", "BUY", 0.123, sl=2640, tp=2670)
    assert res["ok"]
    req = fake.sent[0]
    assert req["volume"] == 0.12  # dibulatkan ke volume_step
    assert req["price"] == 2650.20  # ask
    assert req["type"] == FakeMT5.ORDER_TYPE_BUY
    assert req["type_filling"] == FakeMT5.ORDER_FILLING_FOK


def test_pending_order_requires_price():
    client, _ = make_client(trading_enabled=True)
    with pytest.raises(MT5Error, match="price wajib"):
        client.place_order("XAUUSD", "BUY", 0.1, order_type="LIMIT")


def test_close_and_modify_position():
    client, fake = make_client(trading_enabled=True)
    client.close_position(555, volume=0.05)
    close = fake.sent[-1]
    assert close["type"] == FakeMT5.ORDER_TYPE_SELL and close["position"] == 555
    assert close["volume"] == 0.05
    client.modify_position(555, sl=2645.0)
    mod = fake.sent[-1]
    assert mod["action"] == FakeMT5.TRADE_ACTION_SLTP and mod["sl"] == 2645.0 and mod["tp"] == 2670.0


# ------------------------------------------------------------- MCP server
def test_mcp_tools_registered_and_callable():
    client, _ = make_client()
    server = build_server(client)

    async def run():
        tools = {t.name: t for t in await server.list_tools()}
        assert {"account_info", "place_order", "get_indicators", "calculate_lot_size"} <= tools.keys()
        assert tools["get_tick"].annotations.read_only_hint is True
        assert tools["place_order"].annotations.destructive_hint is True
        res = await server.call_tool("get_indicators", {"symbol": "XAUUSD", "timeframe": "H1"})
        return res

    res = asyncio.run(run())
    text = res.content[0].text if hasattr(res, "content") else res[0].text
    data = json.loads(text)
    assert data["trend"] == "BULLISH"
    assert data["rsi_14"] == 100.0
