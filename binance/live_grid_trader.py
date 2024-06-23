import json
import math
import datetime
import time
import sys
import pickle
import os
import fractions
import decimal
import pandas as pd

from datetime import date
from binance.client import Client
from binance.exceptions import BinanceAPIException 
from requests.exceptions import Timeout

from lib import log
from lib import misc
from lib import kline
from lib import email
from lib.misc import *
from lib.trading import BaseLiveTradingAccount

logging = log.TraceLogging("./data/live_grid_trader_monitor_log.txt")

grid_cfg_pat = '''GRID Configure
    lower_limit:         {lower_limit}
    upper_limit:         {upper_limit}
    start_price:         {start_price}
    stop_profit:         {stop_profit}
    grid_cnt:            {grid_cnt}
    investment:          {investment}
    ----------------------------------------
    Grid Width in USD:   {grid_width_of_usd}
    Grid Width in DCOIN: {grid_width_of_dcoin}
    Profit Per Grid ($): {profit_per_grid_usd:.4f}
    Profit Per Grid (%): {profit_per_grid_ratio:.4f}
    Average Cost:        {avg_cost:.4f}
'''

account_msg_pat = '''Account Info
     FDUSD_LOCKED: {fdusd_locked:.4f}
    *FDUSD_FREE:   {fdusd_free:.4f}
     FDUSD_ASSET:  {fdusd_asset:.4f}
    ----------------------------------------
     {dcoin}_LOCKED:  {dcoin_locked}
    *{dcoin}_FREE:    {dcoin_free}
     {dcoin}_ASSET:   {dcoin_asset} ({dcoin_in_fiat:.4f}$)
     {dcoin}_PRICE:   {dcoin_price:.2f}
    ----------------------------------------
     FIAT_ASSET:  {fiat_asset:.4f}
'''

trade_guard_msg_pat = '''Trading Safe Guard 
     credits: {credits}
'''


history_msg_pat = '''History
    Start Time:        {start_time}
    Bot Age:           {days}
    ----------------------------------------
    Grid Tx Count 1D:  {tx_cnt_1d}
    Grid Tx Count 7D:  {tx_cnt_7d}
    Grid Tx Count 30D: {tx_cnt_30d}
    Grid Tx Count All: {tx_cnt_all}
    Grid Tx Count Avg: {avg_daily_tx:.2f}
    ----------------------------------------
    Grid Profit All:       {grid_profit_all:.4f} $
    GRid Profit 24H ($):   {grid_profit_24h_in_usd:.4f} $
    GRid Profit 24H (%):   {grid_profit_24h_in_ratio:.4f} %
    ----------------------------------------
    Grid APR 1D:       {apr_1d:.2f}%
    Grid APR 7D:       {apr_7d:.2f}%
    Grid APR 30D:      {apr_30d:.2f}%
    Grid APR All:      {apr_all:.2f}%
'''

latest_closed_order_pat = '''Lastest 10 closed orders
{closed_orders}
'''


class Grid:
    def __init__(self):
        self.lower = None
        self.upper = None
        self.init()

    def init(self):
        self.is_buy = None
        self.order_id = None

    def __str__(self):
        msg = "L: {:.2f} H: {:.2f} State: {}".format(self.lower, self.upper, self.get_grid_status_str())
        return msg
    
    def get_grid_status_str(self):
        state = ""
        if self.order_id != None:
            if self.is_buy == True:
                state = "BUY"
            else:
                state = "SEL"
        else:
            state = "NUL"

        return state



class Config:
    def __init__(self, json_config):
        self.json_cfg = json_config
        self.dcoin = json_config['dcoin']
        self.lower_limit = decimal.Decimal(json_config['lower_limit'])
        self.upper_limit = decimal.Decimal(json_config['upper_limit'])
        self.grid_cnt = int(json_config['grid_cnt'])
        self.start_price = decimal.Decimal(json_config['start_price'])
        self.investment = decimal.Decimal(json_config['investment'])
        self.stop_profit = decimal.Decimal(json_config['stop_profit'])
        self.api_key = json_config['api_key']
        self.api_secret = json_config['api_secret']
        self.price_resolution = json_config['price_resolution']
        self.qty_resolution = json_config['qty_resolution']

        # figure out quantity per grid
        self.grid_width_of_usd = round((self.upper_limit - self.lower_limit)/self.grid_cnt, self.price_resolution)
        self.start_grid_id = self.get_grid_id(self.start_price)


        # adjusting the start price to be grid aligned 
        self.start_price = self.lower_limit + self.start_grid_id * self.grid_width_of_usd

        self.grid_width_of_dcoin = self.investment / ((self.grid_cnt - self.start_grid_id)*self.start_price + self.lower_limit * self.start_grid_id + self.start_grid_id * (self.start_grid_id - decimal.Decimal('1'))/decimal.Decimal('2')*self.grid_width_of_usd)
        self.grid_width_of_dcoin = round(self.grid_width_of_dcoin, self.qty_resolution)

        # derived parameters
        self.stop_profit_grid_id = self.get_grid_id(self.stop_profit)

        # valid the trading volume per grid 
        self.validate()

    def validate(self):
        # due to the MIN_NOTIONAL limiation
        if self.grid_width_of_dcoin * self.lower_limit < decimal.Decimal('10.0'):
            logging.log_msg("invalid config, self.grid_width_of_dcoin * self.lower_limit {:.4f} < 10.0".format(self.grid_width_of_dcoin * self.lower_limit))
            assert (0)

    def get_grid_id(self, price):
        grid_id = int((price - self.lower_limit) / self.grid_width_of_usd)
        if grid_id >= self.grid_cnt:
            return self.grid_cnt
        elif grid_id < 0:
            return -1
        else:
            return grid_id

    def get_profit_per_grid_in_usd(self):
        return self.grid_width_of_dcoin * self.grid_width_of_usd

    def get_profit_per_grid_in_ratio(self):
        return self.get_profit_per_grid_in_usd()/self.investment*decimal.Decimal(100)

    def get_avg_cost(self):
        return self.investment / (self.grid_width_of_dcoin * self.grid_cnt)

    def get_grid_cfg_msg(self):
        return grid_cfg_pat.format(lower_limit = self.lower_limit,
                                   upper_limit = self.upper_limit,
                                   start_price = self.start_price,
                                   stop_profit = self.stop_profit,
                                   grid_cnt = self.grid_cnt,
                                   investment = self.investment,
                                   grid_width_of_usd = self.grid_width_of_usd,
                                   grid_width_of_dcoin = self.grid_width_of_dcoin,
                                   profit_per_grid_usd = self.get_profit_per_grid_in_usd(),
                                   profit_per_grid_ratio = self.get_profit_per_grid_in_ratio(),
                                   avg_cost = self.get_avg_cost())

    def show_config(self):
        logging.log_msg(self.get_grid_cfg_msg())


class GridBotDB:
    def __init__(self):
        self.json_cfg = None
        self.start_time = now()


class Account:
    def __init__(self):
        self.fdusd_locked = 0
        self.fdusd_free = 0
        self.fdusd_asset = 0

        self.dcoin_locked = 0
        self.dcoin_free = 0
        self.dcoin_asset = 0

        # derived 
        self.fiat_asset = 0
        self.free_asset = 0

class TradingGuard:
    def __init__(self):
        self.reset()

    def reset(self):
        self.credits = 1000
        self.credit_last_update_time = now()

    def update_credit(self):
        update_window_in_seconds = 12 * 60 * 60
        if int((now() - self.credit_last_update_time).total_seconds()) >= update_window_in_seconds:
            self.reset()

    def is_safe_trading(self):
        self.update_credit()
        if self.credits > 0:
            self.credits -= 1
            return True
        else:
            logging.log_msg("credits are exausted, unsafe trading!!!")
            return False


class History:
    def __init__(self, db, cfg):
        self.db = db
        self.cfg = cfg
        self.closed_orders = []
        self.last_update_time = None
        self.avg_daily_tx = 0

        self.grid_tx_count_1d = 0
        self.grid_tx_count_7d = 0
        self.grid_tx_count_30d = 0
        self.grid_tx_count_total= 0

        self.grid_apr_1d = 0
        self.grid_apr_7d = 0
        self.grid_apr_30d = 0
        self.grid_apr_total = 0

        self.grid_profit_all = 0
        self.grid_profit_last_24h_in_usd = 0
        self.grid_profit_last_24h_in_ratio = 0

    def get_grid_tx_count(self, ma_window_in_days):
        # adjust the MA_WINDOW according to the bot age
        bot_age = self.get_bot_age()
        if bot_age < ma_window_in_days:
            ma_window_in_days = bot_age

        tx_cnt = 0
        ma_window_in_seconds = ma_window_in_days*60*60*24
        current_time = now()

        for order in self.closed_orders:
            order_closed_time = datetime.datetime.fromtimestamp(order['updateTime']/1000)
            if (current_time - order_closed_time).total_seconds() <= ma_window_in_seconds and order['side'] == 'SELL':
                tx_cnt += 1
        return tx_cnt

    def get_grid_apr(self, ma_window_in_days):
        # adjust the MA_WINDOW according to the bot age
        bot_age = self.get_bot_age()
        if bot_age < ma_window_in_days:
            ma_window_in_days = bot_age

        tx_cnt = self.get_grid_tx_count(ma_window_in_days)
        return tx_cnt * self.cfg.grid_width_of_dcoin * self.cfg.grid_width_of_usd/self.cfg.investment/decimal.Decimal(ma_window_in_days) * decimal.Decimal(365 * 100)

    def get_bot_age(self):
        seconds_per_day = 60*60*24
        bot_age = now() - self.db.start_time
        return bot_age.total_seconds()/seconds_per_day


    def get_avg_daily_tx(self):
        return self.grid_tx_count_total / self.get_bot_age()

    def get_grid_profit_all(self):
        return self.grid_tx_count_total*self.cfg.grid_width_of_dcoin*self.cfg.grid_width_of_usd

    def get_grid_profit_last_24h_in_usd(self):
        return self.grid_tx_count_1d*self.cfg.grid_width_of_dcoin*self.cfg.grid_width_of_usd

    def get_grid_profit_last_24h_in_ratio(self):
        return self.get_grid_profit_last_24h_in_usd()/self.cfg.investment*decimal.Decimal(100)


    def update_counters(self):

        # NOTE: must keep the the calling order, otherwise will hit uninitialized variable issue
        self.grid_tx_count_1d = self.get_grid_tx_count(1)
        self.grid_tx_count_7d = self.get_grid_tx_count(7)
        self.grid_tx_count_30d = self.get_grid_tx_count(30)
        self.grid_tx_count_total = self.get_grid_tx_count(self.get_bot_age())
        self.avg_daily_tx = self.get_avg_daily_tx()

        self.grid_apr_1d = self.get_grid_apr(1)
        self.grid_apr_7d = self.get_grid_apr(7)
        self.grid_apr_30d = self.get_grid_apr(30)
        self.grid_apr_total = self.get_grid_apr(self.get_bot_age())

        self.grid_profit_all = self.get_grid_profit_all()
        self.grid_profit_last_24h_in_usd = self.get_grid_profit_last_24h_in_usd()
        self.grid_profit_last_24h_in_ratio = self.get_grid_profit_last_24h_in_ratio()

    def get_latest_closed_orders_msg(self, last_n):
        msg = ""
        for order in self.closed_orders[-last_n:]:
            msg += "    {} {:4s} {} {:.4f}@{:.2f}".format(get_time_str(order['updateTime']), 
                                                          order['side'], 
                                                          self.cfg.dcoin, 
                                                          decimal.Decimal(order['origQty']), 
                                                          decimal.Decimal(order['price']))
            msg += "\n"
        return msg


class GridBot:
    def __init__(self):
        # private
        self.cur_grid_id = None
        self.cur_top_closed_grid_id = None
        self.last_top_closed_grid_id = None
        self.price = None
        self.db = None
        self.cfg_file_name = './config/grid_bot_config.json'
        self.db_file_name = './data/grid_bot.db'
        self.open_orders = []


        # trading safe guard
        self.guard = TradingGuard()

        # load configure
        self.load_config()
        self.symbol = self.cfg.dcoin + "FDUSD"

        # load db
        self.load_db()

        # asset history
        self.asset_csv = "./data/live_grid_trader_asset_{}.csv".format(self.cfg.api_key[-6:])
        self.asset_csv_last_update_time = None
        self.skip_updating_asset_csv = False

        # send email regularly at predefined time
        self.email_send_clock_list = [1, 6, 13, 22]
        self.last_sent_clock = None

        # start history tracking
        self.history = History(self.db, self.cfg)

        # init binance client
        self.client = Client(self.cfg.api_key, self.cfg.api_secret)

        # create grid objects
        self.creat_grid_objects()

        self.account = Account()

        self.validate()

    def validate(self):
        sum_of_usd = 0
        for grid_id in range(0, self.cfg.start_grid_id):
            grid_obj = self.get_grid_object(grid_id)
            sum_of_usd += grid_obj.lower * self.cfg.grid_width_of_dcoin

        start_grid_obj = self.get_grid_object(self.cfg.start_grid_id)

        for grid_id in range(self.cfg.start_grid_id, self.cfg.grid_cnt):
            sum_of_usd += start_grid_obj.lower * self.cfg.grid_width_of_dcoin

        # the sum of usd should be less than the total investment
        assert (sum_of_usd <= self.cfg.investment)



    def load_config(self):
        with open(self.cfg_file_name) as json_file:
            json_config = json.load(json_file)

        self.cfg = Config(json_config)

    def update_db(self):
        with open(self.db_file_name, "wb") as fp:
            pickle.dump(self.db, fp)


    def load_db(self):
        reset_db = True

        if os.path.exists(self.db_file_name):
            with open(self.db_file_name, "rb") as fp:
                reset_db = False
                self.db = pickle.load(fp)


            for key in self.cfg.json_cfg.keys():
                if not key in self.db.json_cfg or self.cfg.json_cfg[key] != self.db.json_cfg[key]:
                    reset_db = True


        if reset_db:
            self.db = GridBotDB()
            self.db.json_cfg = self.cfg.json_cfg
            self.update_db()

    def creat_grid_objects(self):
        self.grids = []

        # creat grid objects
        for i in range(self.cfg.grid_cnt):
            grid = Grid()
            grid.lower = round(self.cfg.lower_limit + i * self.cfg.grid_width_of_usd, self.cfg.price_resolution)
            grid.upper = round(grid.lower + self.cfg.grid_width_of_usd, self.cfg.price_resolution)
            self.grids.append(grid)

    def get_grid_object(self, grid_id):
        if grid_id < 0 or grid_id >= self.cfg.grid_cnt:
            return None
        else:
            return self.grids[grid_id]



    def update_account(self):
        account_info = self.client.get_account()
        for balance in account_info['balances']:
            if balance['asset'] == 'FDUSD':
                self.account.fdusd_free = round(decimal.Decimal(balance['free']), self.cfg.price_resolution)
                self.account.fdusd_locked = round(decimal.Decimal(balance['locked']), self.cfg.price_resolution)
                self.account.fdusd_asset = self.account.fdusd_free + self.account.fdusd_locked
            elif balance['asset'] == self.cfg.dcoin:
                self.account.dcoin_free = round(decimal.Decimal(balance['free']), self.cfg.qty_resolution)
                self.account.dcoin_locked = round(decimal.Decimal(balance['locked']), self.cfg.qty_resolution)
                self.account.dcoin_asset = self.account.dcoin_free + self.account.dcoin_locked

    def update_price(self):
        ticker = self.client.get_ticker(symbol=self.symbol)
        self.price = round(decimal.Decimal(ticker['lastPrice']), self.cfg.price_resolution)
        self.cur_grid_id = self.cfg.get_grid_id(self.price)

        # update fiat asset
        self.account.fiat_asset = self.account.fdusd_asset
        self.account.fiat_asset += (self.account.dcoin_asset * self.price)

        self.account.free_asset = self.account.fdusd_free
        self.account.free_asset += (self.account.dcoin_free * self.price)

    def get_open_orders(self):
        saved_open_orders_cnt = len(self.open_orders)
        self.open_orders = self.client.get_open_orders(symbol=self.symbol)
        # sort open orders by price
        self.open_orders.sort(key=lambda order: decimal.Decimal(order['price']), reverse=False)

        return saved_open_orders_cnt == len(self.open_orders)

    def get_closed_orders(self):
        # this operation is expensive, let's update closed orders every mininute
        update_window_in_seconds = 1 * 60
        if self.history.last_update_time != None and int((now() - self.history.last_update_time).total_seconds()) < update_window_in_seconds:
            return

        saved_closed_orders_count = len(self.history.closed_orders)
        all_orders_in_submit_time = []
        self.history.closed_orders = []

        while True:
            if len(all_orders_in_submit_time) == 0:
                # query all closed orders since self.db.start_time
                startTime = int(self.db.start_time.timestamp()*1000)
            else:
                startTime = int(all_orders_in_submit_time[-1]['time']) + 1

            local_all_orders = self.client.get_all_orders(symbol=self.symbol, startTime=startTime, limit=1000)
            all_orders_in_submit_time.extend(local_all_orders)

            # look up closed orders
            local_closed_orders = []
            for order in local_all_orders:
                if order['status'] == 'FILLED' and self.get_matched_grid_id(order) != None:
                    local_closed_orders.append(order)
                    if self.history.last_update_time == None:
                        logging.log_msg("new closed orderId {}: {}: {:8s} {:4s} {:.4f}@{:.2f}".format(order['orderId'],
                                                                                                      get_time_str(int(order['updateTime'])), 
                                                                                                      order['status'], 
                                                                                                      order['side'], 
                                                                                                      decimal.Decimal(order['origQty']), 
                                                                                                      decimal.Decimal(order['price'])))
            self.history.closed_orders.extend(local_closed_orders)
            if len(local_all_orders) == 0:
                break

        self.history.closed_orders.sort(key=lambda order:order['updateTime'])
        self.history.update_counters()
        self.history.last_update_time = now()

        if saved_closed_orders_count != len(self.history.closed_orders):
            self.send_email()

    def monitor_cycle_start(self):
        self.skip_updating_asset_csv = False

    def monitor_cycle_end(self):
        clock = now().hour
        if clock in self.email_send_clock_list and clock != self.last_sent_clock:
            self.last_sent_clock = clock
            self.send_email()

    def take_snapshot(self):
        while True:
            # update account
            self.update_account()

            # get dcoin price
            self.update_price()

            # get closed orders
            self.get_closed_orders()

            # get open orders
            if self.get_open_orders():
                break

    def send_email(self):
        # don't interrupt my dream. This is my sleeping time!
        clock = now().hour
        if clock >= 14 and clock < 22:
            return
        email_msg = ""
        email_msg += self.cfg.get_grid_cfg_msg()
        email_msg += "\n"
        email_msg += self.get_account_msg()
        email_msg += "\n"
        email_msg += self.get_trade_guard_msg()
        email_msg += "\n"
        email_msg += self.get_history_msg()
        email_msg += "\n"
        email_msg += self.get_latest_closed_orders_msg()

        # email_sender = email.EmailSender()
        # email_sender.send(email_msg)




    def get_progress_bar_str(self):
        percentage_scale = 0.69
        progress_percentage = 100

        grid_obj = self.get_grid_object(self.cur_grid_id)

        if grid_obj == None:
            progress_percentage = 0
        else:
            if grid_obj.is_buy == True:
                lower_price = grid_obj.lower
                upper_price = lower_price + 2* self.cfg.grid_width_of_usd
            else:
                upper_price = grid_obj.upper
                lower_price = upper_price - 2* self.cfg.grid_width_of_usd

            if lower_price != None and upper_price != None:
                progress_percentage = int(100 * (self.price - lower_price) / (upper_price - lower_price))

        plus_char_cnt = int(progress_percentage*percentage_scale)
        minus_char_cnt = int((100-progress_percentage)*percentage_scale) 
        progress_bar_str = "    "
        progress_bar_str += "|" + "+"*plus_char_cnt + "-"*minus_char_cnt + "|"
        return progress_bar_str

    def get_grid_open_orders(self, grid_id):
        order_list = []
        grid_obj = self.get_grid_object(grid_id)

        for open_order in self.open_orders:
            order_price = decimal.Decimal(open_order['price'])
            if grid_obj.lower == order_price and open_order['side'] == "BUY":
                order_list.append(open_order)
            elif grid_obj.upper == order_price and open_order['side'] == "SELL":
                order_list.append(open_order)
        return order_list

    def get_open_order(self, order_id):
        if order_id == None:
            return None

        for open_order in self.open_orders:
            if open_order['orderId'] == order_id:
                return open_order

    def get_account_msg(self):
        return account_msg_pat.format(fdusd_locked = self.account.fdusd_locked,
                                      fdusd_free = self.account.fdusd_free,
                                      fdusd_asset = self.account.fdusd_asset,
                                      dcoin = self.cfg.dcoin,
                                      dcoin_locked = self.account.dcoin_locked,
                                      dcoin_free = self.account.dcoin_free,
                                      dcoin_asset = self.account.dcoin_asset,
                                      dcoin_price = self.price,
                                      dcoin_in_fiat = self.account.dcoin_asset*self.price,
                                      fiat_asset = self.account.fiat_asset)
    def show_account(self):
        logging.log_msg(self.get_account_msg())

    def get_trade_guard_msg(self):
        return trade_guard_msg_pat.format(credits = self.guard.credits)

    def show_trade_guard(self):
        logging.log_msg(self.get_trade_guard_msg())

    def get_history_msg(self):
        return history_msg_pat.format(start_time = datetime_to_str(self.db.start_time),
                                      days = str(now() - self.db.start_time).split('.', 2)[0],
                                      tx_cnt_all = self.history.grid_tx_count_total,
                                      tx_cnt_1d = self.history.grid_tx_count_1d,
                                      tx_cnt_7d = self.history.grid_tx_count_7d,
                                      tx_cnt_30d = self.history.grid_tx_count_30d,
                                      grid_profit_all = self.history.grid_profit_all,
                                      grid_profit_24h_in_usd = self.history.grid_profit_last_24h_in_usd,
                                      grid_profit_24h_in_ratio = self.history.grid_profit_last_24h_in_ratio,
                                      avg_daily_tx = self.history.avg_daily_tx,
                                      apr_1d = self.history.grid_apr_1d,
                                      apr_7d = self.history.grid_apr_7d,
                                      apr_30d = self.history.grid_apr_30d,
                                      apr_all = self.history.grid_apr_total)

    def show_history(self):
        logging.log_msg(self.get_history_msg())

    def get_latest_closed_orders_msg(self):
        return latest_closed_order_pat.format(closed_orders = self.history.get_latest_closed_orders_msg(10))

    def show_latest_closed_orders(self):
        logging.log_msg(self.get_latest_closed_orders_msg())


    def show_grids(self):
        top_sell_grid_id = self.get_top_buy_grid_id() + 1
        logging.log_msg("GRID status")
        for grid_id in reversed(range(self.cfg.grid_cnt)):
            grid_obj = self.get_grid_object(grid_id)
            log_msg = "    [{:<2d}] L: {:.2f} H: {:.2f} State: {}".format(grid_id, grid_obj.lower, grid_obj.upper, grid_obj.get_grid_status_str())

            for open_order in self.get_grid_open_orders(grid_id):
                order_price = decimal.Decimal(open_order['price'])
                order_qty = decimal.Decimal(open_order['origQty'])
                log_msg +=  " {:4s} {} {:.4f}@{:.2f}".format(open_order['side'], self.cfg.dcoin, order_qty, order_price)

            if grid_id >= self.cur_grid_id:
                log_msg += " {:>6.2f}%".format(grid_obj.upper * 100/self.price)
            else:
                log_msg += " {:>6.2f}%".format(grid_obj.lower * 100/self.price)

            if grid_id == self.cfg.stop_profit_grid_id:
                log_msg += "  <= stop  {:.2f}".format(self.cfg.stop_profit)

            if grid_id == self.cfg.start_grid_id:
                log_msg += "  <= start {:.2f}".format(self.cfg.start_price)


            logging.log_msg(log_msg)

            if grid_id == top_sell_grid_id:
                progress_bar_str = self.get_progress_bar_str()
                progress_bar_str += " <= price {:.2f}".format(self.price)
                logging.log_msg(progress_bar_str)


    def show(self):
        logging.log_msg("-"*60)
        logging.log_msg("{}: mode GRID".format(now_str()))

        # show cfg
        self.cfg.show_config()

        # show account
        self.show_account()

        # show guard
        self.show_trade_guard()

        # show history
        self.show_history()

        # show latest closed orders
        self.show_latest_closed_orders()

        # show grids
        self.show_grids()

        # show open orders
        #  self.show_open_orders()


    def show_open_orders(self):
        logging.log_msg("Open orders:")
        for order in self.open_orders:
            order_price = decimal.Decimal(order['price'])
            order_qty = decimal.Decimal(order['origQty'])
            log_msg = "    open order {:4s} {} {:.4f}@{:.2f}".format(order['side'], self.cfg.dcoin, order_qty, order_price)
            logging.log_msg(log_msg)


    def cancel_all_open_orders(self):
        for order in self.open_orders:
            self.cancel_order(order)

    def cancel_order(self, order):
        order_price = decimal.Decimal(order['price'])
        order_qty = decimal.Decimal(order['origQty'])
        order_side = order['side']
        logging.log_msg("{}: cancel order {} {:.4f}@{:.2f}".format(now_str(), order_side, order_qty, order_price))
        result = self.client.cancel_order(symbol=self.symbol, orderId=order['orderId'])

    def buy(self, qty, price):
        # safe guard
        if not self.guard.is_safe_trading():
            return

        trading_msg = "{}: issue BUY {} {:.4f}@{:.2f}".format(now_str(), self.cfg.dcoin, qty, price)
        logging.log_msg(trading_msg)
        order = self.client.order_limit_buy(symbol=self.symbol, quantity=qty, price=price)
        self.skip_updating_asset_csv = True


    def sell(self, qty, price):
        # safe guard
        if not self.guard.is_safe_trading():
            return

        trading_msg = "{}: issue SELL {} {:.4f}@{:.2f}".format(now_str(), self.cfg.dcoin, qty, price)
        logging.log_msg(trading_msg)
        order = self.client.order_limit_sell(symbol=self.symbol, quantity=qty, price=price)
        self.skip_updating_asset_csv = True


    def get_matched_grid_id(self, order):
        for grid_id in range(self.cfg.grid_cnt):
            grid_obj = self.get_grid_object(grid_id)
            order_price = round(decimal.Decimal(order['price']), self.cfg.price_resolution)
            if order['side'] == "BUY" and grid_obj.lower == order_price:
                return grid_id
            elif order['side'] == "SELL" and grid_obj.upper == order_price:
                return grid_id
        return None


    def refresh_grid_orders(self):
        for grid_id in range(self.cfg.grid_cnt):
            grid_obj = self.get_grid_object(grid_id)
            grid_obj.init()

        for order in self.open_orders:
            order_side = order['side']
            order_id = order['orderId']

            grid_id = self.get_matched_grid_id(order)
            if grid_id == None:
                # we should never hit this
                logging.log_msg("unexpected open order!")
                logging.log_msg(str(order))
                assert (0)
                
            grid_obj = self.get_grid_object(grid_id)
            grid_obj.order_id = order_id
            grid_obj.is_buy = True if order_side == "BUY" else False

    def get_sell_order_count(self):
        sell_order_count = 0
        for grid_id in range(self.cfg.grid_cnt):
            grid_obj = self.get_grid_object(grid_id)
            if grid_obj.order_id != None and grid_obj.is_buy == False:
                sell_order_count += 1
        return sell_order_count

    def get_additional_buy_qty(self, first_sell_grid_id):
        # there are two scenarios that need additional buy
        # case1: inital Bot start
        # case2: sell orders are closed, but buy orders are not submitted because of Bot down

        additional_buy_qty = (self.cfg.grid_cnt - first_sell_grid_id) * self.cfg.grid_width_of_dcoin

        # one buy order might just be closed, but the corresponding sell order has not submitted yet. 
        # in order to avoid issuing duplicate buy order, we need to check the dcoin_free
        if self.account.dcoin_asset >= additional_buy_qty:
            additional_buy_qty = 0
        else:
            additional_buy_qty -= self.account.dcoin_asset

        return additional_buy_qty


    def get_top_buy_grid_id(self):
        top_buy_grid_id = -1

        # if all sell orders are closed, meaning we already stop profit, so start next trading cycle from the start grid_id
        if self.get_sell_order_count() == 0:
            top_buy_grid_id = self.cfg.start_grid_id
        else:
            # start from cur_grid_id in backwards to search for closed grid or with buy order open
            # the logic is designed for this case
            # L: 200 H: 300 SEL 300 <= cur_grid_id
            # L: 100 H: 200 SEL 200
            # above case is valid, since when price is 200, cur_grid_id will point to <200, 300>, 
            # but the sell order in <100, 200> might not be closed yet
            for grid_id in range(self.cur_grid_id, -1, -1):
                grid_obj = self.get_grid_object(grid_id)
                if grid_obj.order_id == None or grid_obj.is_buy == True:
                    top_buy_grid_id = grid_id
                    break
        return top_buy_grid_id

    def get_grid_open_orders_qty(self, grid_id):
        qty = decimal.Decimal("0.0")
        for open_order in self.get_grid_open_orders(grid_id):
            qty += decimal.Decimal(open_order['origQty'])
        return qty

    def replenish_buy_orders(self):
        top_buy_grid_id = self.get_top_buy_grid_id()

        fdusd_free = self.account.fdusd_free
        additional_buy_qty = self.get_additional_buy_qty(top_buy_grid_id + 1)
        expected_buy_qty = (top_buy_grid_id + 1) * self.cfg.grid_width_of_dcoin
        expected_buy_qty += additional_buy_qty

        # limit by max_allowed_dcoin_asset
        max_allowed_dcoin_asset = self.cfg.grid_cnt * self.cfg.grid_width_of_dcoin
        if expected_buy_qty + self.account.dcoin_asset > max_allowed_dcoin_asset:
            adjust = expected_buy_qty + self.account.dcoin_asset - max_allowed_dcoin_asset
            expected_buy_qty -= adjust

        logging.log_msg("top_buy_grid_id {}".format(top_buy_grid_id))
        logging.log_msg("additional_buy_qty {:.4f}".format(additional_buy_qty))
        logging.log_msg("expected_buy_qty {:.4f}".format(expected_buy_qty))
        # reopen the closed buy orders
        for grid_id in range(0, top_buy_grid_id+1):
            grid_obj = self.get_grid_object(grid_id)

            # if the buy order is still open, do nothing
            if grid_obj.order_id != None:
                if grid_obj.is_buy != True:
                    logging.log_msg("grid order is not buy order, grid_id {}".format(grid_id))
                    assert (grid_obj.is_buy == True)
                expected_buy_qty -= self.get_grid_open_orders_qty(grid_id)
                if grid_id != top_buy_grid_id:
                    continue

            # submit the buy order
            if grid_id == top_buy_grid_id:
                buy_qty = expected_buy_qty
            else:
                buy_qty = self.cfg.grid_width_of_dcoin

            logging.log_msg("expected_buy_qty {:.4f}".format(expected_buy_qty))
            logging.log_msg("buy_qty {:.4f}".format(buy_qty))
            if buy_qty >= self.cfg.grid_width_of_dcoin:
                # submit buy order
                if fdusd_free >= buy_qty * grid_obj.lower:
                    self.buy(buy_qty, grid_obj.lower)
                    fdusd_free -= buy_qty * grid_obj.lower
                    expected_buy_qty -= buy_qty

                else:
                    logging.log_msg("insuffienct free FDUSD, fdusd_free {:.2f} < buy_qty {:.4f} * buy_price {:.2f}".format(fdusd_free, buy_qty, grid_obj.lower))
                    return


    def replenish_sell_orders(self):
        dcoin_free = self.account.dcoin_free
        skip_additional_buy_order = False

        # open the sell orders
        for grid_id in range(self.cfg.stop_profit_grid_id, self.cur_grid_id-1, -1):
            grid_obj = self.get_grid_object(grid_id)

            if grid_obj == None or grid_obj.order_id != None:
                continue

            if grid_id == self.cfg.stop_profit_grid_id:
                sell_qty = (self.cfg.grid_cnt - self.cfg.stop_profit_grid_id) * self.cfg.grid_width_of_dcoin
            else:
                sell_qty = self.cfg.grid_width_of_dcoin

            if dcoin_free < sell_qty:
                sell_qty = dcoin_free

            if sell_qty >= self.cfg.grid_width_of_dcoin:
                self.sell(sell_qty, grid_obj.upper)
                dcoin_free -= sell_qty
                skip_additional_buy_order = True
            else:
                logging.log_msg("insuffienct free dcoin, dcoin_free {:.4f} sell_qty {:.4f} grid_dcoin {:.4f}".format(dcoin_free, sell_qty, self.cfg.grid_width_of_dcoin))
                return


        if skip_additional_buy_order == True:
            return 

        # find the smallest grid ID whose sell order is open
        additional_sell_grid_id = None
        for grid_id in range(self.cfg.stop_profit_grid_id):
            grid_obj = self.get_grid_object(grid_id)
            if grid_obj.order_id != None and grid_obj.is_buy == False:
                additional_sell_grid_id = grid_id
                break

        if additional_sell_grid_id == None:
            return

        additional_sell_grid_obj = self.get_grid_object(additional_sell_grid_id)

        # submit additional sell order for what we missed during Bot down
        additional_sell_qty = dcoin_free
        if additional_sell_qty >= self.cfg.grid_width_of_dcoin:
            self.sell(additional_sell_qty, additional_sell_grid_obj.upper)

    def cancel_unexpected_orders(self):
        ret = False
        # cancel open orders between start_grid_id and stop_profit_grid_id when we are going to start another trade cycle
        if self.get_sell_order_count() != 0:
            return ret

        for grid_id in range(self.cfg.start_grid_id + 1, self.cfg.stop_profit_grid_id):
            for open_order in self.get_grid_open_orders(grid_id):
                self.cancel_order(open_order)
                ret = True

        return ret

    def replenish_grid_orders(self):
        if self.cancel_unexpected_orders():
            # proceed in next cycle, since the account/orders needs to be refreshed 
            return

        # repair buy orders
        self.replenish_buy_orders()

        # repair sell orders
        self.replenish_sell_orders()


    def grid_engine(self):
        # refresh grid orders
        self.refresh_grid_orders()

        # show status
        self.show()

        # repair grid orders
        self.replenish_grid_orders()


    def close(self):
        self.take_snapshot()
        self.cancel_all_open_orders()
        close_price = self.price + 0.5
        time.sleep(2)
        self.take_snapshot()

        logging.log_msg("closing bot @{:.4f}, current price {:.4f}".format(close_price, self.price))
        self.sell(self.account.dcoin_asset, close_price)
        while True:
            self.take_snapshot()
            if len(self.open_orders) != 0:
                self.show_account()
                self.show_open_orders()
                time.sleep(2)
            else:
                break

        logging.log_msg("bot is closed")
        self.show_account()

    def update_asset_db(self):
        update_window_in_seconds = 1 * 60
        last_update_cycle_id = None

        if self.asset_csv_last_update_time != None:
            last_update_cycle_id = int(self.asset_csv_last_update_time.timestamp() / update_window_in_seconds)

        current_cycle_id = int(now().timestamp()/update_window_in_seconds)


        if current_cycle_id == last_update_cycle_id or self.skip_updating_asset_csv == True:
            return

        # load DB if exist
        if os.path.exists(self.asset_csv):
            asset_db = pd.read_csv(self.asset_csv)
        else:
            asset_db = pd.DataFrame(columns=['DATE', 'Price', 'FDUSD Locked', self.cfg.dcoin, 'FDUSD Free', 'USD$'])

        self.asset_csv_last_update_time = now()
        asset_db.loc[len(asset_db.index)] = [now_str(), self.price, self.account.fdusd_locked, self.account.dcoin_asset, self.account.fdusd_free, self.account.fiat_asset]
        asset_db.to_csv(self.asset_csv, index = False)


    def monitor(self):
        sleep_interval = 2
        while True:
            try:    
                self.monitor_cycle_start()
                self.take_snapshot()
                self.grid_engine()
                self.update_asset_db()
                self.monitor_cycle_end()
                time.sleep(sleep_interval)
            except BinanceAPIException as e:
                logging.log_msg("exception catched")
                logging.log_msg("{}".format(e.status_code))
                logging.log_msg("{}".format(e.message))
            except:
                logging.log_msg("exception catched")
                logging.log_msg("Unexpected error: {}".format(sys.exc_info()[0]))
                time.sleep(sleep_interval)


if __name__ == "__main__":
    # round down
    ctx = decimal.getcontext()
    ctx.rounding = decimal.ROUND_DOWN

    bot = GridBot()
    bot.monitor()
    #  bot.close()
    #  bot.analyze_closed_orders()
    

