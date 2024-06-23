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
JOURNAL_LOG_FILE = "./data/live_ema_monitor_log.txt"

class Epoch:
    def __init__(self):
        self.saved_epoch_id = None
        self.clean()


    def get_cur_epoch_id(self):
        epoch_interval_in_seconds = 15 * 60
        return int(time.time() / epoch_interval_in_seconds)

    def is_new_epoch_id(self):
        updated = False
        cur_epoch_id = self.get_cur_epoch_id()
        if self.saved_epoch_id is None or self.saved_epoch_id != cur_epoch_id:
            self.saved_epoch_id = cur_epoch_id
            return True
        else:
            return False

    def clean(self):
        self.ma = None # moving average 
        self.new_buy_price = None
        self.new_sel_price = None

    def get_buy_price(self):
        return self.new_buy_price

    def get_sell_price(self):
        return self.new_sel_price

    def update_ma(self, ma):
        self.ma = ma

    def get_ma(self):
        return self.ma


class TradingAccount(BaseLiveTradingAccount):
    def __init__(self):
        BaseLiveTradingAccount.__init__(self)
        # load config
        self.load_config()

        self.set_binance_client(Client(self.api_key, self.api_secret))

        self.epoch = Epoch()
        self.set_symbol(SYMBOL)

        self.rt_config_in_last_cycle = None

        self.logging = log.TraceLogging(JOURNAL_LOG_FILE)
        self.asset_csv = "./data/live_ema_asset_{}.csv".format(self.api_key[-6:])
        self.tx_csv = "./data/live_ema_transaction_{}.csv".format(self.api_key[-6:])


    def load_config(self):
        with open('./config/ema_delta_trading_config.json') as json_file:
            config = json.load(json_file)

        self.ma_window = config['ma_window']
        self.ma_alg = config['ma_alg']
        self.mode = config['mode']
        self.buy_delta = config['sell_delta']
        self.sell_delta = config['buy_delta']
        self.stop_buy_price = config['stop_buy_price']
        self.stop_sel_price = config['stop_sel_price']
        self.cooling_down_hours = config['cooling_down_hours']
        self.stop_lost = config['stop_lost']

        self.api_key = config['api_key']
        self.api_secret = config['api_secret']

    def update_epoch(self):
        epoch_id_updated = self.epoch.is_new_epoch_id()
        if epoch_id_updated:
            # hack, get_ema might hit exception because of 1200 requests per min limitation
            self.epoch.clean()

            self.update_account_asset_db(self.asset_csv)
            self.update_transaction_history_db(self.tx_csv)

        if self.mode == "MA" and self.epoch.ma is None:
            if self.ma_alg == "ema":
                ma = self.get_ema(self.ma_window)
            else:
                ma = self.get_sma(self.ma_window)
            self.epoch.update_ma(ma)
            self.epoch.new_buy_price = round(self.epoch.get_ma() - self.buy_delta, 4)
            self.epoch.new_sel_price = round(self.epoch.get_ma() + self.sell_delta, 4)

        if self.mode == "FW" and self.epoch.new_buy_price is None:
            self.epoch.new_buy_price, self.epoch.new_sel_price = self.get_fw_trading_price()
            

    def review_order(self):
        # check if suspended by user
        if self.rt_config != None and self.rt_config_in_last_cycle == None:
            # suspended, cancle all open orders (excluding the cakebusd/cakeusdt orders)
            self.cancel_all_open_orders()
        elif self.rt_config_in_last_cycle != None and self.rt_config == None:
            # update config
            self.mode = self.rt_config_in_last_cycle.mode
            self.ma_window = self.rt_config_in_last_cycle.ma_window
            self.buy_delta = self.rt_config_in_last_cycle.delta
            self.sell_delta = self.rt_config_in_last_cycle.delta
            # refresh epoch
            self.epoch.clean()
            self.update_epoch()

        self.rt_config_in_last_cycle = self.rt_config

        if self.rt_config != None:
            self.logging.log_msg("Auto trading is suspended!!! cancel CAKEBUSD orders to resume")
            return

        # cancel orders if required
        for order in self.open_orders:
            cancel_order = False
            order_price = float(order['price'])
            if order['side'] == 'SELL' and not math.isclose(order_price, self.epoch.get_sell_price(), abs_tol=0.00001):
                cancel_order = True
            if order['side'] == 'BUY' and not math.isclose(order_price, self.epoch.get_buy_price(), abs_tol=0.00001):
                cancel_order = True

            if cancel_order:
                result = self.client.cancel_order(symbol=self.symbol, orderId=order['orderId'])

        # scan the free assets and resubmit new orders
        new_order_submitted = False
        # sell orders
        if self.busd_free >= 10: # BUSDUSDT minimum order limit is 10
            new_order_submitted = True
            self.sell(self.busd_free, self.epoch.get_sell_price())

        # buy orders
        busd_buy = truncate(self.usdt_free/self.epoch.get_buy_price(), 2)
        if busd_buy >= 10:
            new_order_submitted = True
            self.buy(busd_buy, self.epoch.get_buy_price())

        if new_order_submitted:
            self.update_transaction_history_db(self.tx_csv)
        

    def show_account(self):
        self.show_ask_bid()

        if self.mode == "MA":
            log_msg = "{}: MODE {} BUSD {} USDT {} sum {:.2f} ({:.2f}$) price {:.4f} MA {:.4f} BUY_DELTA {:.4f} SEL_DELTA {:.4f} MA_WIN {}".format(
                                                                                 now_str(), 
                                                                                 self.mode,
                                                                                 self.busd_asset, 
                                                                                 self.usdt_asset, 
                                                                                 self.busd_asset + self.usdt_asset, 
                                                                                 self.fiat_asset,
                                                                                 self.last_price, 
                                                                                 self.epoch.ma,
                                                                                 self.buy_delta, 
                                                                                 self.sell_delta, 
                                                                                 self.ma_window)

        elif self.mode == "FW":
            log_msg = "{}: MODE {} BUSD {} USDT {} sum {:.2f} ({:.2f}$) price {:.4f} BUY_PRICE: {:.4f} SEL_PRICE: {:.4f}".format(
                                                                                 now_str(), 
                                                                                 self.mode,
                                                                                 self.busd_asset, 
                                                                                 self.usdt_asset, 
                                                                                 self.busd_asset + self.usdt_asset, 
                                                                                 self.fiat_asset,
                                                                                 self.last_price, 
                                                                                 self.epoch.get_buy_price(),
                                                                                 self.epoch.get_sell_price())
        else:
            assert "no way"

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
        sleep_interval = 5
        while True:
            try:    
                self.take_snapshot()
                self.update_epoch()
                self.review_order()
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

