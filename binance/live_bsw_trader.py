import json
import math
import datetime
import time
import sys
from datetime import date
from binance.client import Client
from binance.exceptions import BinanceAPIException 

from lib import log
from lib import misc
from lib import kline
from lib.misc import *
from lib.trading import BaseLiveTradingAccount

SYMBOL="BUSDUSDT"
JOURNAL_LOG_FILE = "./data/live_bsw_monitor_log.txt"

class TradingAccount(BaseLiveTradingAccount):
    def __init__(self):
        BaseLiveTradingAccount.__init__(self)
        # load config
        self.load_config()

        self.set_binance_client(Client(self.api_key, self.api_secret))

        self.set_symbol(SYMBOL)

        self.logging = log.TraceLogging(JOURNAL_LOG_FILE)


    def load_config(self):
        with open('./config/bsw_trading_config.json') as json_file:
            config = json.load(json_file)

        self.api_key = config['api_key']
        self.api_secret = config['api_secret']

        self.stop_buy_price = 1.0005
        self.stop_sel_price = 0.9980
        self.cooling_down_hours = 4
        self.stop_lost = 0.0004


        self.overwhelm_ratio_h = 4.0
        self.overwhelm_ratio_l = 2.0
        self.absolute_high_qty = 10000000.0

    def eval_buy(self):
        buy = False
        # if any of the conditions below is false, buy is not allowed
        buy_price = self.ask_price_list[0]
        buy_qty = truncate(self.usdt_free/buy_price, 2)

        if buy_qty >= 10 and \
           self.bid_qty_list[0] >= self.absolute_high_qty and \
           self.bid_qty_list[0] >= self.ask_qty_list[0] and \
           get_relative_ratio(self.bid_qty_list[0], self.ask_qty_list[0]) >= self.overwhelm_ratio_h and \
           self.bid_qty_list[0] >= self.ask_qty_list[1]:
               buy = True

        if self.usdt_asset >= 10:
            self.logging.log_msg("eval_buy:")
            self.logging.log_msg("overwhelm_ratio_h: {}".format(self.overwhelm_ratio_h))
            self.logging.log_msg("overwhelm_ratio_l: {}".format(self.overwhelm_ratio_l))
            self.logging.log_msg("absolute_high_qty: {}".format(self.absolute_high_qty))
            self.show_ask_bid()

        if buy:
            self.logging.log_msg("eval_buy: issue BUY order, {:.2f}@{:.4f}".format(buy_qty, buy_price))
            self.buy(buy_qty, buy_price)
        elif self.usdt_locked:
            self.logging.log_msg("eval_buy: cancel all BUY orders")
            self.cancel_all_buy_orders()

    def eval_sell(self):
        if self.busd_asset >= 10:
            self.logging.log_msg("eval_sell:")
            self.logging.log_msg("overwhelm_ratio_h: {}".format(self.overwhelm_ratio_h))
            self.logging.log_msg("overwhelm_ratio_l: {}".format(self.overwhelm_ratio_l))
            self.logging.log_msg("absolute_high_qty: {}".format(self.absolute_high_qty))
            self.show_ask_bid()

        # figure out sell price
        sell_price = None
        bid_vs_ask_min_ratio = 6.0

        if self.ask_qty_list[0] >= self.absolute_high_qty and \
           self.ask_qty_list[0] >= self.bid_qty_list[0] and \
           get_relative_ratio(self.ask_qty_list[0], self.bid_qty_list[0]) >= self.overwhelm_ratio_h:
            sell_price = self.bid_price_list[0]
        elif self.ask_qty_list[0] < self.bid_qty_list[0] and \
             get_relative_ratio(self.ask_qty_list[0], self.bid_qty_list[0]) >= self.overwhelm_ratio_l:
            sell_price = self.ask_price_list[1]
        else:
            sell_price = self.ask_price_list[0]

        # cancel orders if required
        for order in self.open_orders:
            cancel_order = False
            order_price = float(order['price'])
            if order['side'] == 'SELL' and not math.isclose(order_price, sell_price, abs_tol=0.00001):
                cancel_order = True

            if cancel_order:
                self.logging.log_msg("eval_sell: cancel SELL order")
                result = self.client.cancel_order(symbol=self.symbol, orderId=order['orderId'])

        if self.busd_free >= 10:
            self.logging.log_msg("eval_sell: issue SELL order, {:.2f}@{:.4f}".format(self.busd_free, sell_price))
            self.sell(self.busd_free, sell_price)

    def show_account(self):
        log_msg = "{}: BUSD {} USDT {} sum {:.2f} ({:.2f}$) price {:.4f} ".format(
                                                                             now_str(), 
                                                                             self.busd_asset, 
                                                                             self.usdt_asset, 
                                                                             self.busd_asset + self.usdt_asset, 
                                                                             self.fiat_asset,
                                                                             self.last_price)

        log_msg += " ORDERS: "
        for order in self.open_orders:
            order_price = float(order['price'])
            orig_qty = float(order['origQty'])

            if order['side'] == 'SELL':
                order_side = 'SEL'
                self.update_sell_depth(order_price)
                min_order_depth = "None" if self.min_sell_depth is None else int(self.min_sell_depth)
            else:
                order_side = 'BUY'
                self.update_buy_depth(order_price)
                min_order_depth = "None" if self.min_buy_depth is None else int(self.min_buy_depth)

            log_msg += " {} {:.2f}@{:.4f}|{}".format(order_side, orig_qty, order_price, min_order_depth)

        self.logging.log_msg(log_msg)


    def monitor(self):
        sleep_interval = 2
        while True:
            try:    
                self.take_snapshot()
                self.refresh_trading_credits()
                self.eval_buy()
                self.eval_sell()
                self.show_account()
                time.sleep(sleep_interval)
            except BinanceAPIException as e:
                print ("exception catched")
                print (e.status_code)
                print (e.message)
                time.sleep(sleep_interval)
            except:
                print("Unexpected error:", sys.exc_info()[0])
                time.sleep(sleep_interval)

if __name__ == "__main__":
    account = TradingAccount()
    account.monitor()


