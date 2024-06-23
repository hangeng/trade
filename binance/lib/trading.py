from binance.client import Client
from . import kline
import os
import pandas as pd
from .misc import *
import datetime
import random
import time
import json
import pickle
from binance.exceptions import BinanceAPIException 
from requests.exceptions import Timeout


class RTConfig:
    def __init__(self, cakeorder):
        self.cakeorder = cakeorder
        self.mode = None
        self.ma_window = None
        self.delta = None
        self.decode()

        print (str(self))

    def decode(self):
        scale = 1000
        order_price = int(float(self.cakeorder['price']) * scale)

        # price format A.BBC
        # A: odd - MA mode  even - FW mode
        # BB: ma_window
        # C: delta

        self.delta = round(order_price % 10 / 10000, 4)
        self.ma_window = int(order_price / 10) % 100
        self.mode = ["FW", "MA", "BSW", "VCOIN"][int(order_price / 1000) % 10 % 4]

    def __str__(self):
        return "RTConfig: mode {} MA_WIN {} delta {:.4f}".format(self.mode, self.ma_window, self.delta)

class OpenOrder:
    def __init__(self, is_buy):
        self.is_buy_order = is_buy
        self.price = None
        self.queue_depth = None
        self.timestamp = None
        self.need_update_queue_depth = False
    def __str__(self):
        return "is_buy_order: {} price: {} queue_depth: {} timestamp: {} need_update_queue_depth: {}".format(self.is_buy_order,
                                                                                                             self.price,
                                                                                                             self.queue_depth,
                                                                                                             self.timestamp,
                                                                                                             self.need_update_queue_depth)

class VCoinTradingPair:
    def __init__(self, vcoin, policy_cfg):
        ''' vcoin: volatile coin'''
        self.vcoin = vcoin
        self.vcoin_locked = 0
        self.vcoin_free   = 0
        self.vcoin_asset  = 0
        self.vcoin_1hr_high  = 0
        self.vcoin_12hr_high = 0
        self.vcoin_24hr_high = 0
        self.vcoin_price     = 0
        self.policy_cfg = policy_cfg


class VCoinDB:
    def __init__(self):
        self.vcoin = None
        self.vcoin_buy_price = None
        self.vcoin_stop_profit = None
        self.vcoin_sell_price = None
        self.vcoin_buy_timestamp = None
        self.vcoin_buy_timestamp_str = ""
        self.vcoin_trading_frozen_timestamp = None

class BaseLiveTradingAccount:
    def __init__(self):
        self.symbol = None
        self.last_refresh_trading_credits_timestamp = None

        self.open_sell_order = OpenOrder(is_buy=False)
        self.open_buy_order = OpenOrder(is_buy=True)

        self.reset_historical_trades()

        self.last_update_trading_price_timestamp = None
        self.last_buy_price = None
        self.last_sell_price = None

        self.last_update_trading_progress_on_gui_timestamp = None

        self.last_bid_0_price = None
        self.last_ask_0_price = None
        self.last_bid_0_price_change_timestamp = None

        self.vcoin_to_monitor = []
        self.vcoin_trading_pairs = {}
        self.vcoin_db_file_name = "./data/vcoin.db"
        self.vcoin_db = VCoinDB()

    def add_vcoin_trading_pair(self, vcoin, policy_cfg):
        self.vcoin_trading_pairs[vcoin] = VCoinTradingPair(vcoin, policy_cfg)

    def get_vcoin_trading_pair(self, vcoin):
        return self.vcoin_trading_pairs[vcoin]


    def reset_historical_trades(self):
        self.last_historical_trades_timestamp = None
        self.historical_trades = []

    def reset_open_orders(self):
        for open_order in [self.open_buy_order, self.open_sell_order]:
            open_order.price = None
            open_order.timestamp = None
            open_order.queue_depth = None

    def update_account_info(self):
        self.busd_free   = 0
        self.busd_locked = 0
        self.usdt_free   = 0
        self.usdt_locked = 0
        self.cake_free   = 0
        self.cake_locked = 0
        self.bnb_free    = 0
        self.bnb_locked  = 0
        self.busd_asset  = 0
        self.usdt_asset  = 0

        account_info = self.client.get_account()
        for balance in account_info['balances']:
            if balance['asset'] == 'BUSD':
                self.busd_free = truncate(float(balance['free']), 3)
                self.busd_locked = truncate(float(balance['locked']), 3)
                self.busd_asset = self.busd_free + self.busd_locked
            elif balance['asset'] == 'USDT':
                self.usdt_free = truncate(float(balance['free']), 3)
                self.usdt_locked = truncate(float(balance['locked']), 3)
                self.usdt_asset = self.usdt_free + self.usdt_locked
            elif balance['asset'] == 'CAKE':
                self.cake_free = truncate(float(balance['free']), 3)
                self.cake_locked = truncate(float(balance['locked']), 3)
            elif balance['asset'] == 'BNB':
                self.bnb_free = truncate(float(balance['free']), 2)
                self.bnb_locked = truncate(float(balance['locked']), 2)
            elif balance['asset'] in self.vcoin_to_monitor:
                vcoin = balance['asset']
                vcoin_trading_pair = self.get_vcoin_trading_pair(vcoin)
                vcoin_trading_pair.vcoin_free = truncate_float(float(balance['free']), 5)
                vcoin_trading_pair.vcoin_locked = truncate_float(float(balance['locked']), 5)
                vcoin_trading_pair.vcoin_asset = vcoin_trading_pair.vcoin_free + vcoin_trading_pair.vcoin_locked

    def take_snapshot(self):
        sleep_interval = 0.1

        # get account information (Weight 10)
        self.update_account_info()

        time.sleep(sleep_interval)

        # update USDTBUSD order book (Weight 1)
        order_book = self.client.get_order_book(symbol=self.symbol, limit=5)
        self.ask_price_list = []
        self.ask_qty_list = []
        self.bid_price_list = []
        self.bid_qty_list = []

        for ask, bid in zip(order_book['asks'], order_book['bids']):
            self.ask_price_list.append(round(float(ask[0]), 4))
            self.ask_qty_list.append(round(float(ask[1]), 2))

            self.bid_price_list.append(round(float(bid[0]), 4))
            self.bid_qty_list.append(round(float(bid[1]), 2))

        if self.last_bid_0_price != self.bid_price_list[0]:
            self.last_bid_0_price = self.bid_price_list[0]
            self.last_ask_0_price = self.ask_price_list[0]
            self.last_bid_0_price_change_timestamp = now()

        time.sleep(sleep_interval)
        # update open USDTBUSD orders (Weight 3)
        if self.mode != "VCOIN":
            self.open_orders = self.client.get_open_orders(symbol=self.symbol)

        time.sleep(sleep_interval)

        # update last buy/sell price (Weight 10)
        self.update_last_trade_price()

        # update rt_config (Weight 3)
        self.rt_config = None
        if self.cake_locked > 0.1:
            time.sleep(2)
            cakebusd_orders = self.client.get_open_orders(symbol="CAKEBUSD")
            if len(cakebusd_orders) > 0:
                self.rt_config = RTConfig(cakebusd_orders[0])

        # update asset
        self.ask_price = self.ask_price_list[0]
        self.bid_price = self.bid_price_list[0]
        self.last_price = [self.ask_price, self.bid_price][random.randint(0,1)]
        all_busd = self.busd_asset + self.usdt_asset/self.ask_price
        all_usdt = self.usdt_asset + self.busd_asset*self.bid_price
        self.fiat_asset = max(self.busd_asset+self.usdt_asset, all_busd, all_usdt)


        # update historical trades (Weight 1)
        self.update_trading_progress()

        # update vcoin price
        self.update_vcoin_price()

    def update_vcoin_price(self):
        for vcoin in self.vcoin_to_monitor:
            vcoin_trading_pair = self.get_vcoin_trading_pair(vcoin)

            # get 12hr high
            minutes_per_1hr  = 1*60
            minutes_per_12hr = 12*60
            minutes_per_24hr = 24*60
            high_price  = 0

            vcoin_symbol = vcoin+"USDT"
            kl = self.client.get_historical_klines(vcoin_symbol, Client.KLINE_INTERVAL_1MINUTE , "1 day ago UTC")
            time.sleep(0.1)

            for index in range(minutes_per_24hr):
                candle_stick = kline.CandleStick(kl[len(kl)-1-index])

                if high_price < candle_stick.get_high_price():
                    high_price = candle_stick.get_high_price()

                if index <= minutes_per_1hr:
                    vcoin_trading_pair.vcoin_1hr_high = high_price
                elif index <= minutes_per_12hr:
                    vcoin_trading_pair.vcoin_12hr_high = high_price
                elif index <= minutes_per_24hr:
                    vcoin_trading_pair.vcoin_24hr_high = high_price

            # get latest price
            last_candle_stick = kline.CandleStick(kl[-1])
            vcoin_trading_pair.vcoin_price = last_candle_stick.get_close_price()

        #update fiat asset
        if self.mode == "VCOIN":
            self.fiat_asset = self.busd_asset + self.usdt_asset 

            for vcoin in self.vcoin_to_monitor:
                vcoin_trading_pair = self.get_vcoin_trading_pair(vcoin)
                self.fiat_asset += vcoin_trading_pair.vcoin_asset * vcoin_trading_pair.vcoin_price

    def update_last_trade_price(self):
        if self.last_update_trading_price_timestamp is None or (now() - self.last_update_trading_price_timestamp).total_seconds() > 60:
            self.last_update_trading_price_timestamp = now()
            self.last_buy_price = None
            self.last_sell_price = None

            all_orders = self.client.get_all_orders(symbol=self.symbol, limit=500)
            all_orders.reverse()
            for order in all_orders:
                if order['status'] == 'FILLED':
                    order_price = round(float(order['price']), 4)
                    if order['side'] == "BUY" and self.last_buy_price == None:
                        self.last_buy_price = order_price
                    elif order['side'] == "SELL" and self.last_sell_price == None:
                        self.last_sell_price = order_price

    def update_trading_progress(self):
        self.reset_open_orders()

        # update open order price & timestamp
        for order in self.open_orders:
            order_price = round(float(order['price']), 4)
            order_timestamp = int(order['time'])
            open_order = None
            if order['side'] == 'SELL':
                open_order = self.open_sell_order
            else:
                open_order = self.open_buy_order

            open_order.price = order_price
            open_order.timestamp = order_timestamp

        # query DB for queue depth
        for open_order in [self.open_sell_order, self.open_buy_order]:
            if open_order.price == None:
                continue

            db_order = None
            if open_order.is_buy_order:
                db_order = self.db['buy_order']
            else:
                db_order = self.db['sell_order']

            if db_order['price'] != None and db_order['queue_depth'] != None:
                if math.isclose(float(db_order['price']), open_order.price, abs_tol=0.00001):
                    open_order.queue_depth = float(db_order['queue_depth'])

        # check if we need to update queue_depth
        db_updated = False
        for open_order in [self.open_sell_order, self.open_buy_order]:
            if not open_order.need_update_queue_depth:
                continue

            if open_order.price == None:
                continue

            if open_order.is_buy_order:
                price_list = self.bid_price_list
                qty_list = self.bid_qty_list
            else:
                price_list = self.ask_price_list
                qty_list = self.ask_qty_list

            for price, qty in zip(price_list, qty_list):
                if math.isclose(open_order.price, price, abs_tol=0.00001):
                    open_order.queue_depth = qty
                    open_order.need_update_queue_depth = False
                    db_updated = True

        # persist DB
        if db_updated:
            self.dump_open_order_db()

        # query history trades
        if self.last_historical_trades_timestamp == None:
            open_order_timestamps = []
            for open_order in [self.open_buy_order, self.open_sell_order]:
                if open_order.timestamp != None:
                    open_order_timestamps.append(open_order.timestamp)

            if len(open_order_timestamps) > 0:
                self.last_historical_trades_timestamp = min(open_order_timestamps)

        if self.last_historical_trades_timestamp != None:
            # timestamp in milliseconds
            now_timestamp = int(time.time()*1000)
            while self.last_historical_trades_timestamp < now_timestamp:
                start_time = self.last_historical_trades_timestamp
                # NOTE: If both startTime and endTime are sent, time between startTime and endTime must be less than 1 hour.
                if now_timestamp - self.last_historical_trades_timestamp > 3600 * 1000:
                    end_time = self.last_historical_trades_timestamp + 3600 * 1000
                else:
                    end_time = now_timestamp

                aggregated_trades = self.client.get_aggregate_trades(symbol=self.symbol, startTime = start_time, endTime = end_time)
                self.historical_trades += aggregated_trades

                self.last_historical_trades_timestamp = end_time + 1 # inclusive

            #  print ("S"*100)
            #  for trade in self.historical_trades[-100:]:
                #  print ("{} aID {} price {} qty {} {}".format(get_time_str(int(trade['T'])), trade['a'], trade['p'], trade['q'], ['sell', 'buy'][trade['m']]))
            #  print ("E"*100)



    def get_trade_volume(self, is_buy):
            #  [
                #  {
                    #  "a": 26129,         # Aggregate tradeId
                    #  "p": "0.01633102",  # Price
                    #  "q": "4.70443515",  # Quantity
                    #  "f": 27781,         # First tradeId
                    #  "l": 27781,         # Last tradeId
                    #  "T": 1498793709153, # Timestamp
                    #  "m": true,          # Was the buyer the maker?
                    #  "M": true           # Was the trade the best price match?
                #  }
            #  ]
        # If Was the buyer the maker? is true for the trade, 
        # it means that the order of whoever was on the buy side, was sitting as a bid in the orderbook for some time 
        # (so that it was making the market) and then someone came in and matched it immediately (market taker). 
        # So, that specific trade will now qualify as SELL
        start_timestamp = [self.open_sell_order.timestamp, self.open_buy_order.timestamp][is_buy]
        volume = 0
        for trade in self.historical_trades:
            if int(trade['T']) < start_timestamp:
                continue
            if is_buy:
                if trade['m'] and math.isclose(self.open_buy_order.price, float(trade['p']), abs_tol=0.00001):
                    volume += float(trade['q'])
            else:
                if not trade['m'] and math.isclose(self.open_sell_order.price, float(trade['p']), abs_tol=0.00001):
                    volume += float(trade['q'])
        return volume

    def reset_buy_progress(self):
        self.open_buy_order.need_update_queue_depth = True
        self.reset_historical_trades()

    def reset_sell_progress(self):
        self.open_sell_order.need_update_queue_depth = True
        self.reset_historical_trades()

    def get_trade_progress(self, is_buy):
        trade_volume = self.get_trade_volume(is_buy)
        if is_buy:
            open_order = self.open_buy_order
        else:
            open_order = self.open_sell_order

        if open_order.queue_depth != None:
            return truncate(float(100.0*trade_volume/open_order.queue_depth), 2)
        else:
            return 0

    def set_binance_client(self, client):
        self.client = client

    def set_symbol(self, symbol):
        self.symbol = symbol


    def refresh_trading_credits(self):
        if self.last_refresh_trading_credits_timestamp is None or (now() - self.last_refresh_trading_credits_timestamp).total_seconds() > 15 * 60:
            self.trading_credits = 500
            self.last_refresh_trading_credits_timestamp = now()

    def is_safe_trading(self, price, is_buy):
        safe = True

        # freeze trading for 4 seconds once after price changes
        if (now() - self.last_bid_0_price_change_timestamp).total_seconds() <= 4:
            if is_buy and math.isclose(price, self.last_ask_0_price, abs_tol=0.00001):
                safe = False
            elif not is_buy and math.isclose(price, self.last_bid_0_price, abs_tol=0.00001):
                safe = False

        # check safe guard price
        if is_buy:
            if price >= self.stop_buy_price:
                safe = False 
        else:
            if price <= self.stop_sel_price:
                safe = False

        # check trading credits
        self.refresh_trading_credits()
        if self.trading_credits <= 0:
            safe = False
        else:
            self.trading_credits -= 1


        # check stop_lost
        '''
        scale = 10 ** 6
        last_trade_price, last_trade_timestamp = self.get_last_tx(not is_buy)
        last_trade_timestamp_str = datetime.datetime.fromtimestamp(last_trade_timestamp) if last_trade_timestamp != None else "None"
        last_bid_0_price_change_timestamp_str = self.last_bid_0_price_change_timestamp.strftime('%Y-%m-%d %H:%M:%S') if self.last_bid_0_price_change_timestamp != None else "None"

        if last_trade_price != None and (now() - datetime.datetime.fromtimestamp(last_trade_timestamp)).total_seconds() < self.cooling_down_hours * 3600:
            scaled_last_trade_price = last_trade_price * scale
            scaled_price = price * scale
            if is_buy:
                # compare with last sell
                if scaled_price > scaled_last_trade_price and int(scaled_price - scaled_last_trade_price) >= int(self.stop_lost * scale):
                    safe = False
            #  else:
                #  compare with last buy
                #  if scaled_price < scaled_last_trade_price and int(scaled_last_trade_price - scaled_price) >= int(self.stop_lost * scale):
                    #  safe = False
        '''

        if not safe:
            warn_msg  = "*"*20 + "ALERT: unsafe trading" + "*"*20 + "\n"
            warn_msg += ['SEL', 'BUY'][is_buy] + "\n"
            warn_msg += "order_price: {}\n".format(price)
            warn_msg += "stop_buy_price: {}\n".format(self.stop_buy_price)
            warn_msg += "stop_sel_price: {}\n".format(self.stop_sel_price)
            warn_msg += "cooling_down_hours: {}\n".format(self.cooling_down_hours)
            warn_msg += "stop_lost: {}\n".format(self.stop_lost)
            warn_msg += "trading_credits: {}".format(self.trading_credits)
            self.logging.log_msg(warn_msg)
        return safe

    def cancel_all_open_orders(self):
        for order in self.open_orders:
             result = self.client.cancel_order(symbol=self.symbol, orderId=order['orderId'])

    def cancel_all_buy_orders(self):
        for order in self.open_orders:
            if order['side'] == "BUY":
                result = self.client.cancel_order(symbol=self.symbol, orderId=order['orderId'])

    def cancel_all_sell_orders(self):
        for order in self.open_orders:
            if order['side'] == "SELL":
                result = self.client.cancel_order(symbol=self.symbol, orderId=order['orderId'])


    def sell(self, busd_sell, sell_price):
        if not self.is_safe_trading(sell_price, is_buy = False):
            self.cancel_all_open_orders()
            return

        self.reset_sell_progress()

        order = self.client.order_limit_sell(symbol=self.symbol, 
                                             quantity=busd_sell,
                                             price=sell_price)

    def buy(self, busd_buy, buy_price):
        if not self.is_safe_trading(buy_price, is_buy = True):
            self.cancel_all_open_orders()
            return

        self.reset_buy_progress()

        order = self.client.order_limit_buy(symbol=self.symbol, 
                                            quantity=busd_buy,
                                            price=buy_price)

    def get_sma(self, window):
        kl = self.client.get_historical_klines(self.symbol, Client.KLINE_INTERVAL_15MINUTE , "2 day ago UTC")
        klines = kline.Klines(kl)

        return klines.get_close_sma(window)

    def get_ema(self, window):
        kl = self.client.get_historical_klines(self.symbol, Client.KLINE_INTERVAL_15MINUTE , "2 day ago UTC")
        klines = kline.Klines(kl)

        return klines.get_close_ema(window)

    def get_balance_asset(self, asset):
        balance = self.client.get_asset_balance(asset=asset)
        print (asset + ": free:" + balance['free'] + " locked:" + balance['locked'])
        return truncate(float(balance['free']), 2), truncate(float(balance['locked']), 2)

    def update_account_asset_db(self, db_file_name):
        # load DB if exist
        if os.path.exists(db_file_name):
            asset_db = pd.read_csv(db_file_name)
        else:
            asset_db = pd.DataFrame(columns=['DATE', 'BUSD', 'USDT', 'USD$'])

        asset_db.loc[len(asset_db.index)] = [now_str(), self.busd_asset, self.usdt_asset, self.fiat_asset]
        asset_db.to_csv(db_file_name, index = False)

    def get_last_tx(self, is_buy):
        orders = self.client.get_all_orders(symbol=self.symbol, limit=500)
        orders.reverse()
        for order in orders:
            if order['status'] == 'FILLED':
                if (order['side'] == "BUY" and is_buy) or (order['side'] == "SELL" and not is_buy):
                    # price, timestamp
                    return (float(order['price']), int(order['updateTime']/1000))
        return (None, None)


    def update_transaction_history_db(self, db_file_name):
        orders = self.client.get_all_orders(symbol=self.symbol, limit=500)

        rows = []
        for order in orders:
            if order['status'] == 'FILLED':
                new_order = {}
                new_order['symbol'] = order['symbol']
                new_order['time'] = datetime.datetime.fromtimestamp(order['time']/1000).strftime("%Y-%m-%d %H:%M:%S")
                new_order['updateTime'] = datetime.datetime.fromtimestamp(order['updateTime']/1000).strftime("%Y-%m-%d %H:%M:%S")
                new_order['price'] = order['price']
                new_order['side'] = order['side']
                new_order['origQty(BUSD)'] = order['origQty']
                new_order['executedQty(BUSD)'] = order['executedQty']
                new_order['USDT'] = order['cummulativeQuoteQty']
                new_order['clientOrderId'] = order['clientOrderId']
                rows.append(new_order)

        tx_db = pd.DataFrame.from_dict(rows, orient='columns')
        tx_db.to_csv(db_file_name, index = False)

    def get_fw_trading_price(self):
        kl = self.client.get_historical_klines(self.symbol, Client.KLINE_INTERVAL_15MINUTE , "1 day ago UTC", limit=100)
        klines = kline.Klines(kl)

        return klines.get_trading_price_by_candlestick(klines.get_epoch_cnt()-1)

    def is_price_under_trading(self, price):
        for order in self.open_orders:
            order_price = float(order['price'])
            if math.isclose(price, order_price, abs_tol=0.00001):
                return True
        return False

    def show_vcoin_price(self):
        self.logging.log_msg("--------------------")
        for vcoin in self.vcoin_to_monitor:
            vc_pair = self.get_vcoin_trading_pair(vcoin)

            self.logging.log_msg("{} high_24hr:     {} ({:.2f}%)".format(vcoin, int(vc_pair.vcoin_24hr_high), 100.0*vc_pair.vcoin_price/vc_pair.vcoin_24hr_high))
            self.logging.log_msg("{} high_12hr:     {} ({:.2f}%)".format(vcoin, int(vc_pair.vcoin_12hr_high), 100.0*vc_pair.vcoin_price/vc_pair.vcoin_12hr_high))
            self.logging.log_msg("{} high_1hr:      {} ({:.2f}%)".format(vcoin, int(vc_pair.vcoin_1hr_high), 100.0*vc_pair.vcoin_price/vc_pair.vcoin_1hr_high))
            self.logging.log_msg("{} price:         {}".format(vcoin, int(vc_pair.vcoin_price)))
            if self.mode != "VCOIN":
                self.logging.log_msg("{} target:        {}, {}, {}".format(vcoin, int(vc_pair.vcoin_1hr_high * vc_pair.policy_cfg['buy_dip_1hr']), int(vc_pair.vcoin_12hr_high * vc_pair.policy_cfg['buy_dip_12hr']), int(vc_pair.vcoin_24hr_high * vc_pair.policy_cfg['buy_dip_24hr'])))

        if self.mode == "VCOIN":
            self.logging.log_msg("{} buy time :     {}".format(self.vcoin_db.vcoin, self.vcoin_db.vcoin_buy_timestamp_str))
            self.logging.log_msg("{} buy price:     {}".format(self.vcoin_db.vcoin, None if self.vcoin_db.vcoin_buy_price == None else int(self.vcoin_db.vcoin_buy_price)))
            self.logging.log_msg("{} sel price:     {}".format(self.vcoin_db.vcoin, None if self.vcoin_db.vcoin_sell_price == None else int(self.vcoin_db.vcoin_sell_price)))
        self.logging.log_msg("--------------------")

    def show_ask_bid(self):
        level = 3
        self.logging.log_msg("order book:")
        for i in reversed(range(level)):
            self.logging.log_msg("    {}{:.4f} : {}".format(["  ", "->"][self.is_price_under_trading(self.ask_price_list[i])], self.ask_price_list[i], int(self.ask_qty_list[i])))
        self.logging.log_msg("    " + "-"*16)
        for i in range(level):
            self.logging.log_msg("    {}{:.4f} : {}".format(["  ", "->"][self.is_price_under_trading(self.bid_price_list[i])], self.bid_price_list[i], int(self.bid_qty_list[i])))

    def show_trade_volume(self):
        last_bid_0_price_change_timestamp_str = self.last_bid_0_price_change_timestamp.strftime('%Y-%m-%d %H:%M:%S') if self.last_bid_0_price_change_timestamp != None else "None"
        self.logging.log_msg("last price change timestamp: " + last_bid_0_price_change_timestamp_str)

        buy_volume = 0
        sell_volume = 0
        for trade in self.historical_trades:
            if trade['m'] and math.isclose(self.bid_price_list[0], float(trade['p']), abs_tol=0.00001):
                buy_volume += float(trade['q'])
            if not trade['m'] and math.isclose(self.ask_price_list[0], float(trade['p']), abs_tol=0.00001):
                sell_volume += float(trade['q'])

        if len(self.historical_trades) > 0:
            self.logging.log_msg("trading volumes since: " + get_time_str(self.historical_trades[0]['T']))
            self.logging.log_msg("    {:.4f}: {:,}".format(self.ask_price_list[0], int(sell_volume)))
            self.logging.log_msg("    " + "-"*16)
            self.logging.log_msg("    {:.4f}: {:,}".format(self.bid_price_list[0], int(buy_volume)))

    def update_trade_progress_on_gui(self):
        if self.last_update_trading_progress_on_gui_timestamp != None and \
           (now() - self.last_update_trading_progress_on_gui_timestamp).total_seconds() < 120:
            return

        if self.open_sell_order.price != None:
            sell_progress = int(self.get_trade_progress(is_buy=False)) % 100
        else:
            sell_progress = 0

        if self.open_buy_order.price != None:
            buy_progress = int(self.get_trade_progress(is_buy=True)) % 100
        else:
            buy_progress = 0

        self.last_update_trading_progress_on_gui_timestamp = now()

        # in the format 10XX.YY, XX: sell_progress, YY: buy_progress
        if sell_progress >= buy_progress:
            bnb_sell_price = 1100 + sell_progress
        else:
            bnb_sell_price = 1000 + buy_progress


        sleep_interval = 1
        try:
            # cancel order if required
            bnb_symbol = "BNBBUSD"
            if self.bnb_locked > 0:
                bnbbusd_orders = self.client.get_open_orders(symbol=bnb_symbol)
                for order in bnbbusd_orders:
                    self.client.cancel_order(symbol=bnb_symbol, orderId=order['orderId'])

            # issue order 
            bnb_sell_qty = truncate(self.bnb_free + self.bnb_locked, 2)
            if bnb_sell_qty > 0.01:
                self.client.order_limit_sell(symbol=bnb_symbol,
                                             quantity=bnb_sell_qty,
                                             price=bnb_sell_price)
        except BinanceAPIException as e:
            self.logging.log_msg("exception catched")          
            self.logging.log_msg("{}".format(e.status_code))   
            self.logging.log_msg("{}".format(e.message))       
            time.sleep(sleep_interval)
        except:
            self.logging.log_msg("exception catched")
            self.logging.log_msg("Unexpected error: {}".format(sys.exc_info()[0]))

    def refresh_open_order_db(self):
        self.db = {'buy_order': {}, 'sell_order': {}}
        self.db['buy_order']['price'] = self.open_buy_order.price
        self.db['buy_order']['timestamp'] = self.open_buy_order.timestamp
        self.db['buy_order']['queue_depth'] = self.open_buy_order.queue_depth
        self.db['buy_order']['timestamp_str'] = None if self.open_buy_order.timestamp == None else get_time_str(self.open_buy_order.timestamp)

        self.db['sell_order']['price'] = self.open_sell_order.price
        self.db['sell_order']['timestamp'] = self.open_sell_order.timestamp
        self.db['sell_order']['queue_depth'] = self.open_sell_order.queue_depth
        self.db['sell_order']['timestamp_str'] = None if self.open_sell_order.timestamp == None else get_time_str(self.open_sell_order.timestamp)


    def load_open_order_db(self):
        self.db_file_name = './data/open_order_db.json'
        if os.path.exists(self.db_file_name):
            with open(self.db_file_name) as json_file:
                self.db = json.load(json_file)
        else:
            self.refresh_open_order_db()

    def load_vcoin_db(self):
        if os.path.exists(self.vcoin_db_file_name):
            with open(self.vcoin_db_file_name, "rb") as fp:
                self.vcoin_db = pickle.load(fp)
        else:
            self.update_vcoin_db()

    def update_vcoin_db(self):
        with open(self.vcoin_db_file_name, "wb") as fp:
            pickle.dump(self.vcoin_db, fp)

    def dump_open_order_db(self):
        self.refresh_open_order_db()

        with open(self.db_file_name, 'w') as json_file:
            json.dump(self.db, json_file)

    def is_any_partially_filled_orders(self, is_buy):
        for order in self.open_orders:
            if order['status'] == 'PARTIALLY_FILLED':
                if is_buy and order['side'] == 'BUY':
                    return True
                elif not is_buy and order['side'] == 'SELL':
                    return True
        return False
