"""Modul MetaTrader5 palsu untuk pengujian di luar Windows."""

from __future__ import annotations

from collections import namedtuple

Account = namedtuple(
    "Account",
    "login name server currency leverage balance equity margin margin_free margin_level "
    "profit company trade_mode trade_allowed",
)
Terminal = namedtuple("Terminal", "connected trade_allowed company name build ping_last")
Symbol = namedtuple(
    "Symbol",
    "name description visible digits point spread trade_stops_level volume_min volume_max "
    "volume_step trade_contract_size trade_tick_value trade_tick_size currency_base "
    "currency_profit bid ask swap_long swap_short filling_mode",
)
Tick = namedtuple("Tick", "time bid ask last")
Position = namedtuple(
    "Position",
    "ticket symbol type volume price_open price_current sl tp profit swap magic comment time",
)
Result = namedtuple("Result", "retcode comment order deal volume price")
Check = namedtuple("Check", "retcode comment margin margin_free")


class FakeMT5:
    TIMEFRAME_M1, TIMEFRAME_H1, TIMEFRAME_D1 = 1, 16385, 16408
    POSITION_TYPE_BUY, POSITION_TYPE_SELL = 0, 1
    DEAL_TYPE_BUY, DEAL_TYPE_SELL = 0, 1
    ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
    ORDER_TYPE_BUY_LIMIT, ORDER_TYPE_SELL_LIMIT = 2, 3
    ORDER_TYPE_BUY_STOP, ORDER_TYPE_SELL_STOP = 4, 5
    TRADE_ACTION_DEAL, TRADE_ACTION_PENDING, TRADE_ACTION_SLTP, TRADE_ACTION_REMOVE = 1, 5, 6, 8
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
    TRADE_RETCODE_PLACED, TRADE_RETCODE_DONE = 10008, 10009

    def __init__(self, trade_mode: int = 0) -> None:
        self.sent: list[dict] = []
        self.initialized = False
        self.account = Account(
            123, "Agus", "Demo-Server", "USD", 500, 10_000.0, 10_000.0, 0.0, 10_000.0, 0.0,
            0.0, "Broker", trade_mode, True,
        )
        # XAUUSD: 2 digit, 1 lot = 100 oz -> tick 0.01 = $1
        self.symbols = {
            "XAUUSD": Symbol(
                "XAUUSD", "Gold", True, 2, 0.01, 20, 50, 0.01, 100.0, 0.01, 100.0, 1.0, 0.01,
                "XAU", "USD", 2650.00, 2650.20, -30.0, 10.0, 1,
            )
        }
        self.positions = [
            Position(555, "XAUUSD", 0, 0.10, 2640.0, 2650.0, 2630.0, 2670.0, 100.0, 0.0,
                     20260204, "test", 1_764_000_000)
        ]

    # koneksi
    def initialize(self, *args, **kwargs):
        self.initialized = True
        return True

    def shutdown(self):
        self.initialized = False

    def last_error(self):
        return (1, "Success")

    def terminal_info(self):
        return Terminal(True, True, "Broker", "MetaTrader 5", 4000, 12_000) if self.initialized else None

    def account_info(self):
        return self.account

    # simbol
    def symbol_info(self, symbol):
        return self.symbols.get(symbol)

    def symbol_select(self, symbol, enable):
        return True

    def symbols_get(self, group="*"):
        return list(self.symbols.values())

    def symbol_info_tick(self, symbol):
        s = self.symbols[symbol]
        return Tick(1_764_000_000, s.bid, s.ask, 0.0)

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        bars = []
        price = 2600.0
        for i in range(count):
            price += 1.0  # trend naik stabil
            bars.append({
                "time": 1_764_000_000 + i * 3600, "open": price - 0.5, "high": price + 1,
                "low": price - 1, "close": price, "tick_volume": 100, "spread": 20,
            })
        return bars

    # posisi / order
    def positions_get(self, symbol=None, ticket=None):
        out = self.positions
        if symbol:
            out = [p for p in out if p.symbol == symbol]
        if ticket is not None:
            out = [p for p in out if p.ticket == ticket]
        return tuple(out)

    def orders_get(self, symbol=None, ticket=None):
        return ()

    def history_deals_get(self, date_from, date_to):
        return ()

    def order_check(self, request):
        return Check(0, "Done", 52.0, 9_948.0)

    def order_send(self, request):
        self.sent.append(request)
        return Result(self.TRADE_RETCODE_DONE, "Request executed", 1, 2, request.get("volume", 0), request.get("price", 0))
