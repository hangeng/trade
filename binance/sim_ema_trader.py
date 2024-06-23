import statistics
import pandas as pd
import random
import pickle
import math
from binance.client import Client
from lib import log
from lib import misc
from lib import kline
import matplotlib.pyplot as plt


# configures
MA_WINDOW   = 99
MA_ALG      = "sma" # ema or sma
BUY_DELTA = 0.0003
SEL_DELTA = 0.0003
LUCKY_RATIO = 100

print_enabled = True

def disable_print():
    global print_enabled
    print_enabled = False

def enable_print():
    global print_enabled
    print_enabled = True


def print_msg(msg):
    if print_enabled:
        print (msg)


class Trade:
    def __init__(self, timestamp, price, is_sell):
        self.timestamp = timestamp
        self.is_sell = is_sell
        self.price = price


class Order:
    def __init__(self, price, volume, is_sell):
        self.price = price
        self.volume = volume
        self.is_sell = is_sell

    def show(self):
        if self.is_sell:
            print_msg ("orders: SEL vol {} @ {:.4f}".format(self.volume, self.price))
        else:
            print_msg ("orders: BUY vol {} @ {:.4f}".format(self.volume, self.price))

class SimAccount():
    def __init__(self, kl):
        self.klines = kline.Klines(kl)
        self.reset()

    def reset(self):
        self.busd = 10000
        self.usdt = 0
        self.begin_asset = self.busd + self.usdt

        self.ma = None
        self.clock_tick_index = None
        self.begin_time = None

        self.sell_cnt = 0
        self.buy_cnt = 0

        self.last_buy_price = None
        self.last_buy_timestamp = None
        self.last_sel_price = None
        self.last_sel_timestamp = None

        self.cool_down_time = 6 # unit hour
        self.stop_lost_threshhold = 0.0005

        # configures
        self.ma_window = MA_WINDOW
        self.buy_delta = BUY_DELTA
        self.sell_delta = BUY_DELTA
        self.lucky_ratio = LUCKY_RATIO
        self.ma_alg = MA_ALG
        self.klines.set_close_ma_alg(self.ma_alg)

        self.trades = []


    def set_time(self, time):
        if self.begin_time is None:
            self.begin_time = time
        self.now = time

    def now_str(self):
        return self.now.strftime("%Y-%m-%d %H:%M:%S")

    def get_days(self):
        s = self.begin_time
        e = self.now
        return (e - s).days

    def sell(self, price):
        scale = 10 ** 6
        if self.last_buy_price != None and (self.now - self.last_buy_timestamp).total_seconds() < self.cool_down_time * 3600:
            scaled_price = price * scale
            scaled_last_buy_price = self.last_buy_price * scale
            if scaled_price < scaled_last_buy_price and scaled_last_buy_price - scaled_price >= self.stop_lost_threshhold * scale:
                return

        self.sell_order = Order(round(price, 4), int(self.busd), True)

    def buy(self, price):
        scale = 10 ** 6
        if self.last_sel_price != None and (self.now - self.last_sel_timestamp).total_seconds() < self.cool_down_time * 3600:
            scaled_price = price * scale
            scaled_last_sel_price = self.last_sel_price * scale

            if scaled_price >= scaled_last_sel_price and scaled_price - scaled_last_sel_price >= self.stop_lost_threshhold * scale:
                return

        self.buy_order = Order(round(price, 4), int(self.usdt/price), False)

    def refresh_order(self, show_account = False):
        self.sell_order = None
        self.buy_order = None

        self.ma = self.klines.get_close_ma(self.ma_window, self.get_clock_tick() - 1)

        # ----------hack----------------
        #  ma_fluctuation = self.klines.get_ma_fluctuation(7, 4, self.get_clock_tick() - 1)
        #  ma99 = self.klines.get_close_ma(99, self.get_clock_tick() - 1)
        #  ma7 = self.klines.get_close_ma(7, self.get_clock_tick() - 1)

        
        #  if ma_fluctuation > 10:
            #  buy_price = ma99 - 0.0005
            #  sel_price = ma99 + 0.0005
        #  else:
            #  buy_price = ma7 - 0.0001
            #  sel_price = ma7 + 0.0001


        #  print ("ma_99 {}".format(ma99))
        #  print ("ma_7 {}".format(ma7))
        #  print ("{} ma_fluctuation {}".format(self.now_str(), ma_fluctuation))
        #  print ("buy_price {}".format(buy_price))
        #  print ("sel_price {}".format(sel_price))
        #  if self.busd < 10:
            #  self.buy(buy_price)
        #  elif self.usdt < 10:
            #  self.sell(sel_price)
        #  else:
            #  assert "no way"
        #----------------------------------------------
        print ("{} EMA {} delta {}".format(self.now_str(), self.ma, self.buy_delta))
        if self.busd < 10:
            self.buy(self.ma - self.buy_delta)
        elif self.usdt < 10:
            self.sell(self.ma + self.sell_delta)
        else:
            assert "no way"

        #  buy_price, sel_price = self.klines.get_trading_price_by_candlestick(self.get_clock_tick())
        #  if self.busd < 10:
            #  self.buy(buy_price)
        #  elif self.usdt < 10:
            #  self.sell(sel_price)
        #  else:
            #  assert "no way"

        if show_account:
            self.show_account()

    def is_lucky(self):
        return random.randint(0, 100) < self.lucky_ratio

    def execute_buy_order(self, old_price, new_price):
        price_cross = self.buy_order.price >= (new_price + 0.0001) 
        price_lucky = math.isclose(self.buy_order.price, new_price, abs_tol=0.00001) and self.is_lucky()

        if price_cross or price_lucky:
            self.trades.append(Trade(self.now_str(), self.buy_order.price, is_sell=False))
            print_msg ("{} EXEC: buy {} @ {:.4f}".format(self.now_str(), int(self.buy_order.volume), self.buy_order.price))
            self.busd += self.buy_order.volume
            self.usdt -= self.buy_order.volume * self.buy_order.price
            self.buy_cnt += 1
            order_price = self.buy_order.price
            self.last_buy_price = order_price
            self.last_buy_timestamp = self.now

            self.refresh_order(show_account = True)
            self.set_new_price(order_price, new_price)

    def execute_sell_order(self, old_price, new_price):
        price_cross = self.sell_order.price <= (new_price - 0.0001) 
        price_lucky = math.isclose(self.sell_order.price, new_price, abs_tol=0.00001) and self.is_lucky()

        if price_cross or price_lucky:
            self.trades.append(Trade(self.now_str(), self.sell_order.price, is_sell=True))
            print_msg ("{} EXEC: sel {} @ {:.4f}".format(self.now_str(), int(self.sell_order.volume), self.sell_order.price))
            self.busd -= self.sell_order.volume
            self.usdt += self.sell_order.volume * self.sell_order.price
            self.sell_cnt += 1
            order_price = self.sell_order.price
            self.last_sel_price = order_price
            self.last_sel_timestamp = self.now
            self.refresh_order(show_account = True)
            self.set_new_price(order_price, new_price)

    def execute_order(self, old_price, new_price):
        if old_price == new_price:
            return
        elif old_price > new_price and self.buy_order != None:
            self.execute_buy_order(old_price, new_price)
        elif old_price < new_price and self.sell_order != None:
            self.execute_sell_order(old_price, new_price)
            
    def set_new_price(self, old_price, new_price):
        print_msg ("price {:.4f} -> {:.4f}".format(old_price, new_price))
        self.execute_order(old_price, new_price)

    def get_clock_tick(self):
        return self.clock_tick_index

    def clock_tick(self, index):
        self.clock_tick_index = index

        # update time
        self.set_time(self.klines.get_candle_stick(index).get_open_time())

        print_msg ("-"*75)
        print_msg (self.now_str())
        print_msg ("-"*75)

        # refresh order
        self.refresh_order()

        # update price
        candle_stick = self.klines.get_candle_stick(index)
        price_seq = candle_stick.get_price_seqence()

        old_price = self.klines.get_candle_stick(index-1).get_close_price()
        for new_price in price_seq:
            self.set_new_price(old_price, new_price)
            old_price = new_price

        # show account
        self.show_account()

    def get_cur_asset(self):
        price = self.klines.get_candle_stick(self.clock_tick_index).get_close_price()

        all_busd = self.busd + self.usdt / price
        all_usdt = self.busd * price + self.usdt

        return max(all_busd, all_usdt, self.busd + self.usdt)

    def show_trades(self):
        last_sell_price = None
        profit_list = []
        for trade in self.trades:
            if trade.is_sell:
                last_sell_price = trade.price
            else:
                if last_sell_price != None:
                    profit = last_sell_price - trade.price
                    profit_list.append(profit)
                    print (trade.timestamp + " profit: {:.4f}".format(profit))
                    last_sell_price = None

        plt.plot(profit_list, label='profit', color='blue')
        plt.xticks(rotation=45)
        plt.legend(loc='upper left')
        plt.show()



    def monitor(self):

        date_list = []
        roi_list = []
        apr_list = []
        apy_list = []

        #  for i in range(self.ma_window*2+20, self.klines.get_epoch_cnt()):
        for i in range(200, self.klines.get_epoch_cnt()):
            self.clock_tick(i)

            # update report
            date_list.append(self.klines.get_candle_stick(i).get_open_time_str())
            roi_list.append(self.get_roi())
            apr_list.append(self.get_apr())
            apy_list.append(self.get_apy())

        # show trading history
        self.show_trades()

        # save report
        report_df = pd.DataFrame()
        report_df["DATE"] = date_list
        report_df["ROI"] = roi_list
        report_df["APR"] = apr_list
        report_df["APY"] = apy_list

        report_name = "ma_{}_delta_{}_lucky_{}_report.csv".format(self.ma_window, self.sell_delta, self.lucky_ratio)
        report_df.to_csv(report_name, index=False)

    def get_roi(self):
        
        cur_asset = self.get_cur_asset()
        ROI = (cur_asset - self.begin_asset)/self.begin_asset
        return ROI

    def get_apr(self):
        days = self.get_days() + 1

        APR = self.get_roi()/days
        return APR

    def get_apy(self):
        return (1 + self.get_apr()) ** 365 - 1


    def show_account(self):
        print_msg("-"*75)
        print_msg("CONFIG: ma_window {} lucky_ratio {} ma_alg {}".format(self.ma_window, self.lucky_ratio, self.ma_alg))
        print_msg("ma_window   :{}".format(self.ma_window))
        print_msg("sell_delta       :{}".format(self.sell_delta))
        print_msg("buy_delta       :{}".format(self.buy_delta))
        print_msg("lucky_ratio :{}".format(self.lucky_ratio))
        print_msg("ma_alg      :{}".format(self.ma_alg))

        print_msg ("BUSD = {:.2f}, USDT = {:.2f}, MA {:.4f}".format(self.busd, self.usdt, self.ma))

        if self.sell_order:
            self.sell_order.show()
        if self.buy_order:
            self.buy_order.show()

        ROI = self.get_roi()
        APR = self.get_apr()
        APY = self.get_apy()
        print_msg ("sell_cnt = {}, buy_cnt = {}, ROI {:.4f}, APR {:.4f}, APY {:.2f}".format(self.sell_cnt, self.buy_cnt, ROI, APR, APY))

    def compare_ema(self):
        prices = []
        ema = []
        pd_ema = []
        ma = []
        #  for i in range(self.ma_window+1, self.klines.get_epoch_cnt()):
        for i in range(self.ma_window+1, 500):
            ema.append(self.klines.get_close_ema(self.ma_window, i))
            pd_ema.append(self.klines.get_close_pd_ema(self.ma_window, i))
            ma.append(self.klines.get_close_ma(self.ma_window, i))
            prices.append(self.klines.get_candle_stick(i).get_close_price())
        
        plt.figure(figsize=(12.2, 4.5))
        plt.plot(prices,  label='Close') #plt.plot( X-Axis , Y-Axis, line_width, alpha_for_blending,  label)
        plt.plot(ema,  label='EMA') #plt.plot( X-Axis , Y-Axis, line_width, alpha_for_blending,  label)
        plt.plot(ma,  label='ma') #plt.plot( X-Axis , Y-Axis, line_width, alpha_for_blending,  label)
        plt.plot(pd_ema,  label='pd EMA') #plt.plot( X-Axis , Y-Axis, line_width, alpha_for_blending,  label)
        plt.title("moving averge alg comparing")
        plt.legend(loc='upper left')
        plt.show()

    def iterate_all_configs(self):
        report_df = pd.DataFrame()

        ma_window_list = []
        delta_list = []
        lucky_ratio_list = []
        ma_alg_list = []
        roi_list = []
        apr_list = []
        apy_list = []

        for ma_window in range(3, 8):
            for delta in [x * 0.0001 for x in range(1, 6)]:
                for lucky_ratio in range(0, 101, 10):
                    for ma_alg in ["ema", "sma"]:
                        disable_print()
                        self.reset()

                        self.ma_window = ma_window
                        self.delta = round(delta, 4)
                        self.lucky_ratio = lucky_ratio
                        self.ma_alg = ma_alg
                        self.klines.set_close_ma_alg(ma_alg)

                        self.monitor()
                        enable_print()
                        self.show_account()

                        # update report
                        ma_window_list.append(ma_window)
                        delta_list.append(delta)
                        lucky_ratio_list.append(lucky_ratio)
                        ma_alg_list.append(ma_alg)
                        roi_list.append(self.get_roi())
                        apr_list.append(self.get_apr())
                        apy_list.append(self.get_apy())


        # save report
        report_df['ma_window'] = ma_window_list
        report_df['delta'] = delta_list
        report_df['lucky_ratio'] = lucky_ratio_list
        report_df['ma_alg'] = ma_alg_list
        report_df['ROI'] = roi_list
        report_df['APR'] = apr_list
        report_df['APY'] = apy_list
        report_df.to_csv("./all_iteration_report.csv")

    def plt_ma_fluctuation(self, f_window):
        ma_fluctuation = []
        prices = []
        ma_list = []
        timestamps = []
        for i in range(100, self.klines.get_epoch_cnt()):
            self.clock_tick_index = i
            ma_fluctuation.append(self.klines.get_ma_fluctuation(self.ma_window, f_window, i))
            ma_list.append(self.klines.get_close_ma(self.ma_window, i, without_round_up=True))
            prices.append(self.klines.get_candle_stick(i).get_close_price())
            timestamps.append(self.klines.get_candle_stick(i).get_open_time_str())

        print ("ma_fluctuation median {}".format(statistics.median(ma_fluctuation)))

        plt.figure(figsize=(12.2,4.5)) #width = 12.2in, height = 4.5

        plt_cycles_start = 300
        plt_cycles_end = 1
        ax1 = plt.subplot(2, 1, 1)
        ax1.plot(timestamps[-plt_cycles_start:-plt_cycles_end], prices[-plt_cycles_start:-plt_cycles_end], label='prices', color='blue')
        ax1.plot(timestamps[-plt_cycles_start:-plt_cycles_end], ma_list[-plt_cycles_start:-plt_cycles_end], label='ma_list', color='black')

        ax2 = plt.subplot(2, 1, 2, sharex=ax1)
        ax2.plot(timestamps[-plt_cycles_start:-plt_cycles_end], ma_fluctuation[-plt_cycles_start:-plt_cycles_end], label='MA_FLUCTUATION', color = 'red')

        plt.xticks(rotation=45)
        plt.legend(loc='upper left')
        plt.show()

    def above_and_cross_percent(self, price):
        cnt = 0
        for i in range(self.klines.get_epoch_cnt()):
            candle = self.klines.get_candle_stick(i)
            if price >= candle.get_low_price() and price <= candle.get_high_price() or price < candle.get_low_price():
                cnt += 1
        return cnt / self.klines.get_epoch_cnt() * 100

    def below_and_cross_percent(self, price):
        cnt = 0
        for i in range(self.klines.get_epoch_cnt()):
            candle = self.klines.get_candle_stick(i)
            if price >= candle.get_low_price() and price <= candle.get_high_price() or price > candle.get_high_price():
                cnt += 1
        return cnt / self.klines.get_epoch_cnt() * 100

    def summary_cross(self):
        for price in [1 + x * 0.0001 for x in range(30, -30, -1)]:
            a_c = self.above_and_cross_percent(price)
            b_c = self.below_and_cross_percent(price)
            print ("price {:.4f}: a_c {:.2f} b_c {:.2f}".format(price, a_c, b_c))



if __name__ == "__main__":
    with open("./klines/busdusdt_klines.pkl", "rb") as tf:
        kl = pickle.load(tf)

    account = SimAccount(kl)
    #  account.compare_ema()
    #  account.iterate_all_configs()
    account.monitor()
    #  account.plt_ma_fluctuation(16)
    #  account.summary_cross()

