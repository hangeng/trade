import datetime
import pandas as pd
from .misc import *


class PriceTrending:
    UP      = 0
    DOWN    = 1
    OTHERS  = 2


class CandleStick:
    def __init__(self, kline):
        self.kline = kline

    def get_open_time_str(self):
        d = datetime.datetime.fromtimestamp(self.kline[0]/1000 + 12*3600)
        return d.strftime("%Y-%m-%d %H:%M:%S")

    def get_open_time(self):
        return datetime.datetime.fromtimestamp(self.kline[0]/1000 + 12*3600)

    
    def get_open_price(self):
        return round(float(self.kline[1]), 4)

    def get_close_price(self):
        return round(float(self.kline[4]), 4)

    def get_high_price(self):
        return round(float(self.kline[2]), 4)
    
    def get_low_price(self):
        return round(float(self.kline[3]), 4)

    def get_volume(self):
        return float(self.kline[5])

    def get_price_seqence(self):
        o = self.get_open_price()
        c = self.get_close_price()
        h = self.get_high_price()
        l = self.get_low_price()

        if c > o:
            price_seq = [o, l, h, c]
        else:
            price_seq = [o, h, l, c]
        return price_seq



    def __str__(self):
        return "{}: o/h/l/c {}/{}/{}/{}".format(self.get_open_time_str(), self.get_open_price(), self.get_high_price(), self.get_low_price(), self.get_close_price())


class Klines:
    def __init__(self, klines):
        self.klines = klines

    def get_close_pd_ema(self, window, index = None, without_round_up = False):
        if index is not None:
            assert index >= window
            assert index < len(self.klines)
        else:
            index = -1
        klines_for_ema = self.klines[index - window:index]

        close_prices = [CandleStick(k).get_close_price() for k in klines_for_ema]
        close_prices_df = pd.DataFrame(close_prices)

        ema_df = close_prices_df.ewm(span=window).mean() 
        return round(ema_df.values.tolist()[-1][0], 4)

    def get_close_ema(self, window, index = None, without_round_up = False):

        if index is not None:
            assert index >= window
            assert index < len(self.klines)
        else:
            index = -1
        klines_for_ma = self.klines[index - window:index] # remove the latest epoch

        close_price = [CandleStick(kline).get_close_price() for kline in klines_for_ma]

        ema = [sum(close_price) / len(close_price)]
        for price in close_price:
            ema.append((price * (2 / (1 + window))) + ema[-1] * (1 - (2 / (1 + window))))

        if without_round_up:
            return ema[-1]
        else:
            return round(ema[-1], 4)

    def get_close_sma(self, window, index = None, without_round_up = False):
        if index is not None:
            assert index >= window
            assert index < len(self.klines)
        else:
            index = -1
        klines_for_ma = self.klines[index - window:index] # remove the latest epoch
        close_price = [CandleStick(kline).get_close_price() for kline in klines_for_ma]

        if without_round_up:
            return sum(close_price) / len(close_price)
        else:
            return round(sum(close_price) / len(close_price), 4)


    def get_ma_fluctuation(self, ma_window, f_window, index = None):
        # ma_window: the window to cauculate ma
        # f_window: the window to cauculate flucutation
        scale = 10**6

        ma_list = []
        for i in range(f_window):
            ma_list.append(self.get_close_ma(ma_window, index - f_window + i, without_round_up=True))

        ma_fluctuation = 0
        for i in range(f_window-1):
            ma_fluctuation += abs(ma_list[i+1] * scale - ma_list[i]*scale)
        #  return int(ma_fluctuation/(f_window-1))
        return ma_fluctuation/(f_window-1)


    def set_close_ma_alg(self, alg):
        alg_map = {"ema": self.get_close_ema,
                   "sma": self.get_close_sma}
        self.ma_alg = alg_map[alg]

    def get_close_ma(self, window, index = None, without_round_up = False):
        return self.ma_alg(window, index, without_round_up)

    def get_epoch_cnt(self):
        return len(self.klines)

    def get_candle_stick(self, index):
        return CandleStick(self.klines[index])

    def update_prices(self, candle_stick, prices_dict, weight):
        o = candle_stick.get_open_price()
        c = candle_stick.get_close_price()
        h = candle_stick.get_high_price()
        l = candle_stick.get_low_price()

        for price in [o, c]:
            if price in prices_dict:
                prices_dict[price] += 2 * weight
            else:
                prices_dict[price] = 2 * weight

        for price in [h, l]:
            if price in [o, c]:
                continue

            if price in prices_dict:
                prices_dict[price] += 1 * weight
            else:
                prices_dict[price] = 1 * weight

    def select_top3_prices_by_hitting_counters(self, prices_dict):
        if len(prices_dict) < 3:
            return None

        sorted_prices = sorted(prices_dict.items(), key=lambda x: x[1], reverse=True)

        #  print (sorted_prices)
        if len(sorted_prices) >= 4:
            # make sure the hitting countor of #4 prices is not the same as the #3
            if sorted_prices[3][1] == sorted_prices[2][1]:
                return None

        return [sorted_prices[0][0], sorted_prices[1][0], sorted_prices[2][0]]

    def evaulate_price_trending(self, ma_list):
        assert len(ma_list) == 3

        ma_delta = 0
        trend = []
        for i in range(len(ma_list)-1):
            ma_delta += abs(ma_list[i] - ma_list[i+1])
            if math.isclose(ma_list[i], ma_list[i+1], abs_tol=0.00001):
                trend.append(0)
            elif ma_list[i] > ma_list[i+1]:
                trend.append(1)
            else:
                trend.append(-1)

        # normalize and scale
        ma_delta /= (len(ma_list) - 1)
        ma_delta *= 10000


        #  print ("ma_list: " + str(ma_list))
        #  print ("ma_delta {:.4f} trend {}".format(ma_delta, sum(trend)))

        trending = None

        if sum(trend) == 2 and ma_delta >= 0.75:
            trending = PriceTrending.UP
        elif sum(trend) == -2 and ma_delta >= 0.75:
            trending = PriceTrending.DOWN
        else:
            trending = PriceTrending.OTHERS

        print ("Trend: {}".format(["UP", "DOWN", "OTHERS"][trending]))
        return trending

    def predict_prices(self, prices_dict):
        # sort rule: sort the item by hitting count in the reverse order. If the hitting cnt is the same
        #            sort by prices. we always prefer making the trading price lower
        sorted_hitcnt_and_price = sorted(prices_dict.items(), key=lambda x: x[1]-x[0], reverse=True)

        #  print (sorted_hitcnt_and_price)

        candidate_prices = []
        for i in range(min(len(sorted_hitcnt_and_price), 3)):
            candidate_prices.append(sorted_hitcnt_and_price[i][0])

        buy_price = min(candidate_prices)
        sel_price = max(candidate_prices)

        return (buy_price, sel_price)

    def get_trading_price_by_candlestick(self, index):
        prices_dict = {}

        solid_price_set = set()
        buy_price = None
        sel_price = None

        # update prices by the latest 3 candleSticks
        for i in range(3):
            candle_stick = self.get_candle_stick(index - i - 1)
            self.update_prices(candle_stick, prices_dict, [0.5, 0.3, 0.2][i])

        i = 3
        while len(prices_dict) < 3:
            candle_stick = self.get_candle_stick(index - i - 1)
            self.update_prices(candle_stick, prices_dict, 0.2)
            i += 1

        # predict the sell/buy prices
        buy_price, sel_price = self.predict_prices(prices_dict)

        '''
        # adjusting the prices by 7-window MA trending
        ma_list = []
        for i in range(3):
            ma_list.append(self.get_close_sma(7, index - i, without_round_up = True))


        price_trending = self.evaulate_price_trending(ma_list)

        candle_stick = self.get_candle_stick(index-1)

        if price_trending == PriceTrending.UP:
            buy_price = candle_stick.get_close_price() - 0.0001
            sel_price = buy_price + 0.0003
        elif price_trending == PriceTrending.DOWN:
            buy_price = candle_stick.get_close_price() - 0.0002
            sel_price = candle_stick.get_close_price() + 0.0001
        '''

        buy_price = round(buy_price, 4)
        sel_price = round(sel_price, 4)

        candle_stick = self.get_candle_stick(index)
        #  print ("{} buy_price: {} sel_price: {}".format(candle_stick.get_open_time_str(), buy_price, sel_price))
        return (buy_price, sel_price)

