import pickle
from lib import log
from lib import macd_engine
from lib import misc
from lib import candle 
from binance.client import Client

class TradingAccount:
    def __init__(self, klines):
        self.klines = klines
        self.logging = log.TraceLogging("./sim_monitor_log.txt")
        self.macd_gen = macd_engine.MacdGenerator(klines)
        self.trade_policy_maker = macd_engine.TradePolicyMaker()
        self.trade_policy_maker.set_logging(self.logging)
        self.busd = 10000
        self.usdt = 0
        self.last_trade_price = None
        self.immediate_price = None
        self.now = None


    def buy(self):
        self.logging.log_msg("EXEC: BUY {:.2f} @ {:.4f}".format(self.usdt, self.trade_policy_maker.immediate_buy_price))
        self.busd += self.usdt/self.trade_policy_maker.immediate_buy_price
        self.usdt = 0
        self.last_trade_price = self.trade_policy_maker.immediate_buy_price

    def sell(self):
        self.logging.log_msg("EXEC: SEL {:.2f} @ {:.4f}".format(self.busd, self.trade_policy_maker.immediate_sell_price))
        self.usdt += self.busd * self.trade_policy_maker.immediate_sell_price
        self.busd = 0
        self.last_trade_price = self.trade_policy_maker.immediate_sell_price


    def clock_tick(self, index):
        MACD_TREND_CYCLE = 15 

        if index < MACD_TREND_CYCLE + 1:
            return

        kline = candle.Candle(self.klines[index])
        self.now = kline.get_open_time_str()
        self.immediate_price = kline.get_open_price()
        self.trade_policy_maker.set_immediate_buy_price(kline.get_close_price() + 0.0001)
        self.trade_policy_maker.set_immediate_sell_price(kline.get_close_price() - 0.0001)
        self.trade_policy_maker.set_last_trade_price(self.last_trade_price)
        self.trade_policy_maker.set_macd(self.macd_gen.get_macd()[index-MACD_TREND_CYCLE:index+1])
        self.trade_policy_maker.set_signal(self.macd_gen.get_signal()[index-MACD_TREND_CYCLE:index+1])

        if self.busd > 0:
            if self.trade_policy_maker.is_able_to_sell():
                self.sell()
        else:
            if self.trade_policy_maker.is_able_to_buy():
                self.buy()

        self.show()

    def show(self):
        busd_asset = self.busd
        usdt_asset = self.usdt

        all_busd = busd_asset + usdt_asset/self.trade_policy_maker.immediate_buy_price
        all_usdt = usdt_asset + busd_asset*self.trade_policy_maker.immediate_sell_price

        fiat_asset = max(busd_asset+usdt_asset, all_busd, all_usdt)

        log_msg = "{}: BUSD {} USDT {} sum {:.2f} ({:.2f}$) price {:.4f}".format(self.now, 
                                                                                 busd_asset, 
                                                                                 usdt_asset, 
                                                                                 busd_asset + usdt_asset, 
                                                                                 fiat_asset,
                                                                                 self.immediate_price)
        self.logging.log_msg(log_msg)


    def monitor(self):
        for i in range(len(self.klines)):
            self.clock_tick(i)

if __name__ == "__main__":
    with open("./busd_klines.pkl", "rb") as tf:
        klines = pickle.load(tf)
    account = TradingAccount(klines)
    account.monitor()

