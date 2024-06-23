import json
import math
import datetime
import time
import sys
import pickle
from datetime import date
from binance.client import Client
from binance.exceptions import BinanceAPIException 
from requests.exceptions import Timeout

from lib import log
from lib import misc
from lib import kline
from lib.misc import *
from lib.trading import BaseLiveTradingAccount

SYMBOL="BUSDUSDT"
JOURNAL_LOG_FILE = "./data/live_trader_monitor_log.txt"

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

        # load kv store
        self.load_open_order_db()

        # load vcoin DB
        self.load_vcoin_db()

        self.set_binance_client(Client(self.api_key, self.api_secret))

        self.epoch = Epoch()
        self.set_symbol(SYMBOL)

        self.rt_config_in_last_cycle = None

        self.logging = log.TraceLogging(JOURNAL_LOG_FILE)
        self.asset_csv = "./data/live_ema_asset_{}.csv".format(self.api_key[-6:])
        self.tx_csv = "./data/live_ema_transaction_{}.csv".format(self.api_key[-6:])

        self.buy_partially_filled_indicator = 0
        self.sell_partially_filled_indicator = 0

        self.last_refresh_vcoin_trading_credits_timestamp = None


    def load_config(self):
        with open('./config/trade_config.json') as json_file:
            config = json.load(json_file)

        self.config = config
        self.ma_window = config['ma_window']
        self.ma_alg = config['ma_alg']
        self.mode = config['mode']
        self.buy_delta = config['sell_delta']
        self.sell_delta = config['buy_delta']
        self.stop_buy_price = config['stop_buy_price']
        self.stop_sel_price = config['stop_sel_price']
        self.cooling_down_hours = config['cooling_down_hours']

        self.overwhelm_ratio_h = config['overwhelm_ratio_h']
        self.overwhelm_ratio_l = config['overwhelm_ratio_l']
        self.absolute_high_qty = config['absolute_high_qty']
        self.absolute_low_qty  = config['absolute_low_qty']

        self.api_key = config['api_key']
        self.api_secret = config['api_secret']

        self.vcoin_to_monitor = config['vcoin_to_monitor']
        for vcoin in self.vcoin_to_monitor:
            self.add_vcoin_trading_pair(vcoin, config[vcoin])


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

    def is_suspended(self):
        # check if suspended by user
        if self.rt_config != None and self.rt_config_in_last_cycle == None:
            # suspended, cancle all open orders (excluding the cakebusd/cakeusdt orders)
            #  self.cancel_all_open_orders()
            pass
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
            return True
        else:
            return False

            
    def excute_mode_engine(self):
        if self.is_suspended():
            return

        if self.mode == "MA" or self.mode == "FW":
            self.ma_and_fw_engine()
        elif self.mode == "BSW":
            self.bsw_engine()
        elif self.mode == "VCOIN":
            self.vcoin_engine()
        else:
            self.logging.log_msg("unknown mode:" + self.mode)



    def ma_and_fw_engine(self):
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
        sell_qty = truncate(self.busd_free, 2)
        if sell_qty >= 10: # BUSDUSDT minimum order limit is 10
            new_order_submitted = True
            self.sell(sell_qty, self.epoch.get_sell_price())

        # buy orders
        busd_buy = truncate(self.usdt_free/self.epoch.get_buy_price(), 2)
        if busd_buy >= 10:
            new_order_submitted = True
            self.buy(busd_buy, self.epoch.get_buy_price())

        if new_order_submitted:
            self.update_transaction_history_db(self.tx_csv)

    def bsw_engine(self):
        self.bsw_engine_eval_buy()
        self.bsw_engine_eval_sell()

        
    def bsw_engine_eval_buy(self):
        if self.usdt_asset >= 10:
            self.logging.log_msg("eval_buy:")
            self.logging.log_msg("overwhelm_ratio_h: {}".format(self.overwhelm_ratio_h))
            self.logging.log_msg("overwhelm_ratio_l: {}".format(self.overwhelm_ratio_l))
            #  self.logging.log_msg("absolute_high_qty: {}".format(self.absolute_high_qty))
            #  self.logging.log_msg("absolute_low_qty:  {}".format(self.absolute_low_qty))

        # case 1: if the biding qty is overwhelmingly greater (overwhelm_ratio_h) than the asking qty
        if self.bid_qty_list[0] >= self.ask_qty_list[0] and \
           get_relative_ratio(self.bid_qty_list[0], self.ask_qty_list[0]) >= self.overwhelm_ratio_h:
                buy_price = self.ask_price_list[0]

        # case 2: if the biding qty is comparable with the asking qty
        elif (self.bid_qty_list[0] >= self.ask_qty_list[0]) or \
             (self.bid_qty_list[0] < self.ask_qty_list[0] and \
              get_relative_ratio(self.bid_qty_list[0], self.ask_qty_list[0]) <= (self.overwhelm_ratio_l + self.overwhelm_ratio_h)/2.0):
                buy_price = self.bid_price_list[0]

        # case 3: default
        else:
                buy_price = self.bid_price_list[1]



        # cancel orders if required
        order_canceled = False
        for order in self.open_orders:
            order_price = float(order['price'])
            if order['side'] == 'BUY' and not math.isclose(order_price, buy_price, abs_tol=0.00001):
                self.logging.log_msg("{} eval_buy: cancel BUY order, {}@{}".format(now_str(), order['origQty'], order['price']))
                order_canceled = True
                try:
                    result = self.client.cancel_order(symbol=self.symbol, orderId=order['orderId'])
                except BinanceAPIException as e:
                    self.logging.log_msg("exception catched")
                    self.logging.log_msg("{}".format(e.status_code))
                    self.logging.log_msg("{}".format(e.message))
                except:
                    self.logging.log_msg("Unexpected error: {}".format(sys.exc_info()[0]))


        
        # if there is any partially filled SELL orders, wait until all the SELL orders close
        if self.is_any_partially_filled_orders(is_buy=False):
            self.sell_partially_filled_indicator = 0
        else:
            self.sell_partially_filled_indicator += 1

        if not order_canceled and self.sell_partially_filled_indicator < 2:
            self.logging.log_msg("eval_buy: waiting partially filled orders to close")
            return

        if order_canceled:
            buy_qty = truncate(self.usdt_asset/buy_price, 2)
        else:
            buy_qty = truncate(self.usdt_free/buy_price, 2)

        if buy_qty*buy_price >= 10:
            self.logging.log_msg("{} eval_buy: issue BUY order, {:.2f}@{:.4f}".format(now_str(), buy_qty, buy_price))
            self.buy(buy_qty, buy_price)

    def bsw_engine_eval_sell(self):
        if self.busd_asset >= 10:
            self.logging.log_msg("eval_sell:")
            self.logging.log_msg("overwhelm_ratio_h: {}".format(self.overwhelm_ratio_h))
            self.logging.log_msg("overwhelm_ratio_l: {}".format(self.overwhelm_ratio_l))
            #  self.logging.log_msg("absolute_high_qty: {}".format(self.absolute_high_qty))
            #  self.logging.log_msg("absolute_low_qty:  {}".format(self.absolute_low_qty))
            self.logging.log_msg("last_buy_price:    {}".format(self.last_buy_price))

        # figure out sell price
        sell_price = None

        if self.ask_qty_list[0] >= self.bid_qty_list[0] and \
           get_relative_ratio(self.ask_qty_list[0], self.bid_qty_list[0]) >= (self.overwhelm_ratio_l + self.overwhelm_ratio_h)/2.0:
            sell_price = self.bid_price_list[0]

        elif self.last_buy_price != None and \
             math.isclose(self.ask_price_list[0], self.last_buy_price + 0.0001, abs_tol=0.00001) and \
             self.ask_qty_list[0] < self.bid_qty_list[0] and \
             get_relative_ratio(self.ask_qty_list[0], self.bid_qty_list[0]) <= (self.overwhelm_ratio_l + self.overwhelm_ratio_h)/2.0:
            sell_price = self.ask_price_list[0]

        elif self.ask_qty_list[0] < self.bid_qty_list[0] and \
             get_relative_ratio(self.ask_qty_list[0], self.bid_qty_list[0]) >= self.overwhelm_ratio_l:
            sell_price = self.ask_price_list[1]

        else:
            sell_price = self.ask_price_list[0]

        # cancel orders if required
        order_canceled = False
        for order in self.open_orders:
            order_price = float(order['price'])
            if order['side'] == 'SELL' and not math.isclose(order_price, sell_price, abs_tol=0.00001):
                order_canceled = True
                self.logging.log_msg("{} eval_sell: cancel SELL order, {}@{}".format(now_str(), order['origQty'], order['price']))
                try:
                    result = self.client.cancel_order(symbol=self.symbol, orderId=order['orderId'])
                except BinanceAPIException as e:
                    self.logging.log_msg("exception catched")
                    self.logging.log_msg("{}".format(e.status_code))
                    self.logging.log_msg("{}".format(e.message))
                except:
                    self.logging.log_msg("exception catched")
                    self.logging.log_msg("Unexpected error: {}".format(sys.exc_info()[0]))

        # if there is any partially filled BUY orders, wait until all the BUY orders close
        if self.is_any_partially_filled_orders(is_buy=True):
            self.buy_partially_filled_indicator = 0
        else:
            self.buy_partially_filled_indicator += 1

        if not order_canceled and self.buy_partially_filled_indicator < 2:
            self.logging.log_msg("eval_sell: waiting partially filled orders to close")
            return

        if order_canceled:
            sell_qty = truncate(self.busd_asset, 2)
        else:
            sell_qty = truncate(self.busd_free, 2)

        if sell_qty >= 10:
            self.logging.log_msg("{} eval_sell: issue SELL order, {}@{:.4f}".format(now_str(), sell_qty, sell_price))
            self.sell(sell_qty, sell_price)

    def show_account(self):
        self.show_vcoin_price()

        if self.mode != "VCOIN":
            self.show_ask_bid()
            self.show_trade_volume()
            self.update_trade_progress_on_gui()

        if self.mode == "MA":
            log_msg = "{}: MODE {} BUSD {:.3f} USDT {:.3f} sum {:.3f} ({:.3f}$) price {:.4f} MA {:.4f} BUY_DELTA {:.4f} SEL_DELTA {:.4f} MA_WIN {}".format(
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
            log_msg = "{}: MODE {} BUSD {:.3f} USDT {:.3f} sum {:.3f} ({:.3f}$) price {:.4f} BUY_PRICE: {:.4f} SEL_PRICE: {:.4f}".format(
                                                                                 now_str(), 
                                                                                 self.mode,
                                                                                 self.busd_asset, 
                                                                                 self.usdt_asset, 
                                                                                 self.busd_asset + self.usdt_asset, 
                                                                                 self.fiat_asset,
                                                                                 self.last_price, 
                                                                                 self.epoch.get_buy_price(),
                                                                                 self.epoch.get_sell_price())
        elif self.mode == "BSW":
            log_msg = "{}: MODE {} BUSD {:.3f} USDT {:.3f} sum {:.3f} ({:.3f}$) price {:.4f} ".format(
                                                                                 now_str(), 
                                                                                 self.mode,
                                                                                 self.busd_asset, 
                                                                                 self.usdt_asset, 
                                                                                 self.busd_asset + self.usdt_asset, 
                                                                                 self.fiat_asset,
                                                                                 self.last_price)
        elif self.mode == "VCOIN":
            vcoin = self.vcoin_db.vcoin
            vc_pair = self.get_vcoin_trading_pair(vcoin)
            log_msg = "{}: MODE {} BUSD {:.3f} USDT {:.3f} {} {:.5f} current price {} sum {:.3f}".format(
                                                                                 now_str(),
                                                                                 self.mode,
                                                                                 self.busd_asset, 
                                                                                 self.usdt_asset, 
                                                                                 vcoin,
                                                                                 vc_pair.vcoin_asset,
                                                                                 int(vc_pair.vcoin_price),
                                                                                 int(self.fiat_asset))
        else:
            assert "no way"

        log_msg += " ORDERS: "
        if self.mode == "VCOIN":
            for order in self.open_orders:
                order_price = int(float(order['price']))
                order_timestamp = int(order['time'])
                order_time_stamp_str = get_time_str(order_timestamp)
                orig_qty = float(order['origQty'])
                order_symbol = order['symbol']
                if order['side'] == 'SELL':
                    order_side = 'SEL'
                    trade_progress = self.get_trade_progress(is_buy=False)
                    trade_volume = self.get_trade_volume(is_buy=False)
                else:
                    order_side = 'BUY'
                    trade_progress = self.get_trade_progress(is_buy=True)
                    trade_volume = self.get_trade_volume(is_buy=True)

                log_msg += " {} {} {:.4f}@{}|{}".format(order_side, order_symbol, orig_qty, order_price, order_time_stamp_str)

        else:
            for order in self.open_orders:
                order_price = float(order['price'])
                order_timestamp = int(order['time'])
                order_time_stamp_str = get_time_str(order_timestamp)
                orig_qty = float(order['origQty'])

                if order['side'] == 'SELL':
                    order_side = 'SEL'
                    open_order_qdepth = "None" if self.open_sell_order.queue_depth is None else int(self.open_sell_order.queue_depth)
                    trade_progress = self.get_trade_progress(is_buy=False)
                    trade_volume = self.get_trade_volume(is_buy=False)
                else:
                    order_side = 'BUY'
                    open_order_qdepth = "None" if self.open_buy_order.queue_depth is None else int(self.open_buy_order.queue_depth)
                    trade_progress = self.get_trade_progress(is_buy=True)
                    trade_volume = self.get_trade_volume(is_buy=True)

                if trade_progress != 0:
                    log_msg += " {} {:.2f}@{:.4f}|{}({}% - {})".format(order_side, orig_qty, order_price, open_order_qdepth, trade_progress, order_time_stamp_str)
                else:
                    log_msg += " {} {:.2f}@{:.4f}|{}({:.2f} - {})".format(order_side, orig_qty, order_price, open_order_qdepth, trade_volume, order_time_stamp_str)


        self.logging.log_msg(log_msg)

    def vcoin_engine(self):
        exit_vcoin_mode = True
        vcoin = self.vcoin_db.vcoin
        vc_pair = self.get_vcoin_trading_pair(vcoin)

        # update open orders
        self.open_orders = self.client.get_open_orders(symbol=vcoin+"USDT")
        time.sleep(0.3)
        self.open_orders += self.client.get_open_orders(symbol=vcoin+"BUSD")
        time.sleep(0.3)

        # cancel buy orders if they are not closed in 5 mins
        for open_order in self.open_orders:
            if open_order['side'] == 'BUY':
                exit_vcoin_mode=False
                # unit: milliseconds
                order_time = int(open_order['time'])
                now_timestamp = int(time.time()*1000)
                buy_order_open_tolerant_ms = self.config['buy_order_open_tolerant_minutes']*60*1000
                if now_timestamp > (order_time + buy_order_open_tolerant_ms):
                    # cancel the buy order
                    self.logging.log_msg("open order time expired, canceling {} buy order: {}@{}".format(vcoin, open_order['origQty'], open_order['price']))
                    self.client.cancel_order(symbol=open_order['symbol'], orderId=open_order['orderId'])


        # eval sell price
        stop_loss_price = int(self.vcoin_db.vcoin_buy_price * vc_pair.policy_cfg['stop_loss'])
        stop_profit_price = int(self.vcoin_db.vcoin_buy_price * self.vcoin_db.vcoin_stop_profit)

        if vc_pair.vcoin_price < stop_loss_price:
            sell_price = stop_loss_price
        else:
            sell_price = stop_profit_price

        # revisit the sell order
        for open_order in self.open_orders:
            if open_order['side'] == 'SELL':
                exit_vcoin_mode=False
                order_price = int(float(open_order['price']))
                if order_price != sell_price:
                    # cancel the sell order
                    self.logging.log_msg("canceling {} sell order: {}@{}".format(vcoin, open_order['origQty'], open_order['price']))
                    self.client.cancel_order(symbol=open_order['symbol'], orderId=open_order['orderId'])

        # submit sell order
        if vc_pair.vcoin_free >= 0.0001:
            exit_vcoin_mode=False

            vcoin_busd_qty = truncate_float(vc_pair.vcoin_free, 4)
            if sell_price == stop_loss_price:
                if self.is_vcoin_trading_safe():
                    # sell with the market price immediately
                    self.client.order_market_sell(symbol=vcoin+"BUSD",
                                                  quantity=vcoin_busd_qty)
                    self.vcoin_trading_credits -= 1
            else:
                if self.is_vcoin_trading_safe():
                    self.client.order_limit_sell(symbol=vcoin+"BUSD",
                                                 quantity=vcoin_busd_qty,
                                                 price=sell_price)
                    self.vcoin_trading_credits -= 1
            self.logging.log_msg("SELL {}BUSD {:.4f}@{:.2f}".format(vcoin, vcoin_busd_qty, sell_price))
            self.vcoin_db.vcoin_sell_price = sell_price
            self.update_vcoin_db()

        # if need to switch working mode
        if exit_vcoin_mode:
            if self.vcoin_db.vcoin_sell_price == stop_loss_price:
                # fail, frozen one week
                self.vcoin_db.vcoin_trading_frozen_timestamp = time.time()*1000 + int(vc_pair.policy_cfg['stop_trading_days_after_fail']*24*60*60*1000)
                self.update_vcoin_db()
            self.logging.log_msg("="*20)
            self.logging.log_msg("switch back to BSW mode")
            self.mode = "BSW"


    def refresh_vcoin_trading_credits(self):
        if self.last_refresh_vcoin_trading_credits_timestamp is None or (now() - self.last_refresh_vcoin_trading_credits_timestamp).total_seconds() > 15 * 60:
            self.vcoin_trading_credits = 6
            self.last_refresh_vcoin_trading_credits_timestamp = now()


    def is_vcoin_trading_safe(self):
        if self.vcoin_trading_credits <= 0:
            self.logging.log_msg("not safe for vcoin trading")
            return False
        return True

    def monitor_vcoin(self):
        now_timestamp = int(time.time()*1000)
        if self.mode == "VCOIN":
            return
        elif self.vcoin_db.vcoin_trading_frozen_timestamp != None and now_timestamp < self.vcoin_db.vcoin_trading_frozen_timestamp:
            frozen_hours_left = (self.vcoin_db.vcoin_trading_frozen_timestamp - now_timestamp)*1.0/1000/60/60
            self.logging.log_msg("************ VCOIN Trading is Frozen in {:.1f} hours **************".format(frozen_hours_left))
            return
        else:
            # if there is opening VCOIN orders, it should working on VCOIN mode, or the account has vcoin asset
            for vcoin in self.vcoin_to_monitor:
                vcoin_trading_pair = self.get_vcoin_trading_pair(vcoin)
                open_orders = self.client.get_open_orders(symbol=vcoin+"USDT")
                open_orders += self.client.get_open_orders(symbol=vcoin+"BUSD")
                if len(open_orders) > 0 or vcoin_trading_pair.vcoin_asset >= 0.0001:
                    self.mode = "VCOIN"
                    return

        switch_to_vcoin_mode = False
        # check if need to switch to VCOIN mode
        for vcoin in self.vcoin_to_monitor:
            vc_pair = self.get_vcoin_trading_pair(vcoin)
            buy_dip_1hr = vc_pair.policy_cfg['buy_dip_1hr']
            buy_dip_12hr = vc_pair.policy_cfg['buy_dip_12hr']
            buy_dip_24hr = vc_pair.policy_cfg['buy_dip_24hr']
            name_TBD = vc_pair.policy_cfg['name_TBD']

            # proactively switch to vcoin mode
            buy_dip_1hr_ahead_buffer  = self.config['buy_dip_1hr_ahead_buffer']
            buy_dip_12hr_ahead_buffer  = self.config['buy_dip_12hr_ahead_buffer']
            buy_dip_24hr_ahead_buffer  = self.config['buy_dip_24hr_ahead_buffer']

            if vc_pair.vcoin_price <= vc_pair.vcoin_1hr_high * (buy_dip_1hr+buy_dip_1hr_ahead_buffer) and vc_pair.vcoin_price >= vc_pair.vcoin_12hr_high * name_TBD:
                switch_to_vcoin_mode = True

                # remember the vcoin, buy_price and timestamp
                self.vcoin_db.vcoin = vcoin
                self.vcoin_db.vcoin_stop_profit = vc_pair.policy_cfg['stop_profit_1hr']
                self.vcoin_db.vcoin_buy_price = int(vc_pair.vcoin_1hr_high * buy_dip_1hr)
                self.vcoin_db.vcoin_buy_timestamp = now()
                self.vcoin_db.vcoin_buy_timestamp_str = now_str()
                self.update_vcoin_db()

            elif vc_pair.vcoin_price <= vc_pair.vcoin_12hr_high * (buy_dip_12hr+buy_dip_12hr_ahead_buffer):
                switch_to_vcoin_mode = True

                # remember the vcoin, buy_price and timestamp
                self.vcoin_db.vcoin = vcoin
                self.vcoin_db.vcoin_stop_profit = vc_pair.policy_cfg['stop_profit_12hr']
                self.vcoin_db.vcoin_buy_price = int(vc_pair.vcoin_12hr_high * buy_dip_12hr)
                self.vcoin_db.vcoin_buy_timestamp = now()
                self.vcoin_db.vcoin_buy_timestamp_str = now_str()
                self.update_vcoin_db()

            elif vc_pair.vcoin_price <= vc_pair.vcoin_24hr_high * (buy_dip_24hr+buy_dip_24hr_ahead_buffer):
                switch_to_vcoin_mode = True

                # remember the vcoin, buy_price and timestamp
                self.vcoin_db.vcoin = vcoin
                self.vcoin_db.vcoin_stop_profit = vc_pair.policy_cfg['stop_profit_24hr']
                self.vcoin_db.vcoin_buy_price = int(vc_pair.vcoin_24hr_high * buy_dip_24hr)
                self.vcoin_db.vcoin_buy_timestamp = now()
                self.vcoin_db.vcoin_buy_timestamp_str = now_str()
                self.update_vcoin_db()

            if switch_to_vcoin_mode:
                break


        if switch_to_vcoin_mode:
            vcoin = self.vcoin_db.vcoin
            vc_pair = self.get_vcoin_trading_pair(vcoin)

            # cancel all USDTBUSD open orders
            self.logging.log_msg("="*20)
            self.logging.log_msg("{} 24hr_high: {} 12hr_high: {} 1hr_high: {}, switching to VCOIN ({}) mode".format(now_str(), int(vc_pair.vcoin_24hr_high), int(vc_pair.vcoin_12hr_high), int(vc_pair.vcoin_1hr_high), vcoin))
            self.cancel_all_open_orders()

            time.sleep(0.1)
            # update account info
            self.update_account_info()

            time.sleep(0.1)

            # buy vcoin immediately
            buy_price = self.vcoin_db.vcoin_buy_price

            commission_fees_reserve = 20
            if self.busd_free > 30:
                # buy through busd
                if self.is_vcoin_trading_safe():
                    vcoin_busd_qty = truncate_float((self.busd_free-commission_fees_reserve)/buy_price, 4)
                    self.client.order_limit_buy(symbol=vcoin+"BUSD",
                                                quantity=vcoin_busd_qty,
                                                price=buy_price)
                    self.vcoin_trading_credits -= 1
                    self.logging.log_msg("BUY {}BUSD {:.4f}@{:.2f}".format(vcoin, vcoin_busd_qty, buy_price))

            if self.usdt_free > 30:
                # buy BUSD first
                busd_buy_price = self.ask_price_list[0]
                if busd_buy_price < 1.0010:
                    busd_buy_qty = int(self.usdt_free / busd_buy_price)
                    self.client.order_limit_buy(symbol="BUSDUSDT",
                                                quantity=busd_buy_qty,
                                                price=busd_buy_price)
                    time.sleep(3)
                    self.update_account_info()
                    time.sleep(0.1)

                    if self.busd_free > 30:
                        if self.is_vcoin_trading_safe():
                            # buy through busd
                            vcoin_busd_qty = truncate_float((self.busd_free-commission_fees_reserve)/buy_price, 4)
                            self.client.order_limit_buy(symbol=vcoin+"BUSD",
                                                        quantity=vcoin_busd_qty,
                                                        price=buy_price)
                            self.vcoin_trading_credits -= 1
                            self.logging.log_msg("BUY {}BUSD {:.4f}@{:.2f}".format(vcoin, vcoin_busd_qty, buy_price))
                else:
                    if self.is_vcoin_trading_safe():
                        # buy through USDT
                        vcoin_usdt_qty = truncate_float((self.usdt_free-commission_fees_reserve)/buy_price, 4)
                        self.client.order_limit_buy(symbol=vcoin+"USDT",
                                                    quantity=vcoin_usdt_qty,
                                                    price=buy_price)
                        self.vcoin_trading_credits -= 1
                        self.logging.log_msg("BUY {}USDT {:.4f}@{:.2f}".format(vcoin, vcoin_usdt_qty, buy_price))

            # switch mode
            self.mode = "VCOIN"

            # update account info
            self.update_account_info()
            time.sleep(0.1)

    def monitor(self):
        sleep_interval = 0.1
        while True:
            try:    
                self.take_snapshot()
                self.update_epoch()
                self.show_account()
                self.refresh_vcoin_trading_credits()
                self.monitor_vcoin()
                self.excute_mode_engine()
                time.sleep(sleep_interval)
            except BinanceAPIException as e:
                self.logging.log_msg("exception catched")
                self.logging.log_msg("{}".format(e.status_code))
                self.logging.log_msg("{}".format(e.message))
            except:
                self.logging.log_msg("exception catched")
                self.logging.log_msg("Unexpected error: {}".format(sys.exc_info()[0]))
                time.sleep(sleep_interval)

if __name__ == "__main__":
    account = TradingAccount()
    account.monitor()

