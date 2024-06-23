import pandas as pd
from .candle import Candle

FORCE_SELL_PRICE = 0.9999
FORCE_BUY_PRICE  = 0.9983

STOP_BUY_PRICE  = 0.9995
STOP_SELL_PRICE = 0.9983

STOP_PROFIT_PRICE = 0.0010
MACD_CEIL       = 200
MACD_FLOOR      = -150

MACD_TREND_CYCLE = 15

class MacdGenerator:
    def __init__(self, klines):
        self.klines = klines
        self.generate_macd()

    def generate_macd(self):
        prices = []
        for kline in self.klines:
            candle = Candle(kline)
            prices.append(candle.get_close_price())

        prices_df = pd.DataFrame(prices)
        day12 = prices_df.ewm(span=12).mean() 
        day26 = prices_df.ewm(span=26).mean()

        macd = []  # List to hold the MACD line values

        counter=0  # Loop to substantiate the MACD line
        while counter < (len(day12)):
            macd.append(day12.iloc[counter,0] - day26.iloc[counter,0])  # Subtract the 26 day EW moving average from the 12 day.
            counter += 1

        macd_df = pd.DataFrame(macd)
        signal_df = macd_df.ewm(span=9).mean() # Create the signal line, which is a 9 day EW moving average
        signal = signal_df.values.tolist()  # Add the signal line values to a list.
        signal = [x[0] for x in signal]

        #scale the MACD and signal
        self.macd = [x * 10 ** 6 for x in macd]
        self.signal = [x * 10 ** 6 for x in signal]

    def get_macd(self):
        return self.macd
    
    def get_signal(self):
        return self.signal

class TradePolicyMaker:
    def __init__(self):
        self.macd = None
        self.signal = None
        self.immediate_buy_price = None
        self.immediate_sell_price = None
        self.last_trade_price = None
        self.logging = None
        self.force_sell_price = FORCE_SELL_PRICE
        self.force_buy_price = FORCE_BUY_PRICE
        self.stop_buy_price = STOP_BUY_PRICE
        self.stop_sell_price = STOP_SELL_PRICE
        self.stop_profit_price = STOP_PROFIT_PRICE
        self.macd_ceil = MACD_CEIL
        self.macd_floor = MACD_FLOOR
        self.macd_trend_cycle = MACD_TREND_CYCLE

    def set_immediate_buy_price(self, price):
        self.immediate_buy_price = price

    def set_immediate_sell_price(self, price):
        self.immediate_sell_price = price

    def set_last_trade_price(self, price):
        self.last_trade_price = price

    def set_macd(self, macd):
        self.macd = macd

    def set_signal(self, signal):
        self.signal = signal

    def set_logging(self, logging):
        self.logging = logging

    def apply_macd_indicator(self, is_buy):
        self.logging.log_msg("-"*75)
        self.logging.log_msg("MACD_CEIL: {} MACD_FLOOR: {} MACD_TREND_CYCLE: {}".format(MACD_CEIL, MACD_FLOOR, MACD_TREND_CYCLE))

        df = pd.DataFrame()
        df['macd'] = self.macd[-self.macd_trend_cycle-1:]
        df['signal'] = self.signal[-self.macd_trend_cycle-1:]
        self.logging.log_msg(str(df))

        ret = self.__apply_macd_indicator_v2(is_buy)

        self.logging.log_msg("{} apply_macd_indicator: {}".format(['SEL', 'BUY'][is_buy], ret))
        return ret
    

    def __apply_macd_indicator_v2(self, is_buy):
        if is_buy:
            if self.macd[-1] < self.signal[-1] and abs(self.signal[-1] - self.macd[-1]) > 50:
                return True
        else:
            if self.macd[-1] > self.signal[-1] and abs(self.macd[-1] - self.signal[-1]) > 100:
                return True
        return False

    def __apply_macd_indicator(self, is_buy):
        if is_buy:
            if self.macd[-1] <= MACD_FLOOR:
                return True
        else:
            if self.macd[-1] >= MACD_CEIL:
                return True

        # x-cross?
        x_cross = False
        if is_buy:
            if self.macd[-2] < self.signal[-2] and self.macd[-1] > self.signal[-1]:
                x_cross = True
        else:
            if self.macd[-2] > self.signal[-2] and self.macd[-1] < self.signal[-1]:
                x_cross = True

        
        if not x_cross:
            return False


        # review the last 10 macd/signal
        macd_vs_signal = []
        for i in range(2, self.macd_trend_cycle+2):
            if self.macd[-i] > self.signal[-i]:
                macd_vs_signal.append(1)
            elif self.macd[-i] < self.signal[-i]:
                macd_vs_signal.append(-1)
            else:
                macd_vs_signal.append(0)

        if is_buy:
            if sum(macd_vs_signal) == -self.macd_trend_cycle:
                return True
        else:
            if sum(macd_vs_signal) == self.macd_trend_cycle:
                return True

        return False

    def apply_price_indicator(self, is_buy):
        self.logging.log_msg("-"*75)
        self.logging.log_msg("cur_BUY_price:     {:.4f}".format(self.immediate_buy_price))
        self.logging.log_msg("cur_SEL_price:     {:.4f}".format(self.immediate_sell_price))
        self.logging.log_msg("last_TRADE_price:  {}".format(self.last_trade_price))
        self.logging.log_msg("force_BUY_price:   {:.4f}".format(self.force_buy_price))
        self.logging.log_msg("force_SEL_price:   {:.4f}".format(self.force_sell_price))
        self.logging.log_msg("stop_profit_price: {:.4f}".format(self.stop_profit_price))

        ret = self.__apply_price_indicator(is_buy)

        self.logging.log_msg("{} apply_price_indicator: {}".format(['SEL', 'BUY'][is_buy], ret))

        return ret


    def __apply_price_indicator(self, is_buy):
        if is_buy:
            if self.immediate_buy_price <= self.force_buy_price:
                return True
            #  if self.immediate_buy_price <= (self.last_trade_price - self.stop_profit_price):
                #  indicator = True
        else:
            if self.immediate_sell_price >= self.force_sell_price:
                return True
            if self.last_trade_price != None and self.immediate_sell_price >= (self.last_trade_price + self.stop_profit_price):
                return True
        return False

    def __apply_safe_guard(self, is_buy):
        if is_buy:
            if self.immediate_buy_price >= self.stop_buy_price:
                return False
        else:
            if self.immediate_sell_price <= self.stop_sell_price:
                return False
        return True

    def apply_safe_guard(self, is_buy):
        self.logging.log_msg("-"*75)
        self.logging.log_msg("stop_BUY_price:    {:.4f}".format(self.stop_buy_price))
        self.logging.log_msg("stop_SEL_price:    {:.4f}".format(self.stop_sell_price))

        ret = self.__apply_safe_guard(is_buy)

        self.logging.log_msg("{} apply_safe_guard: {}".format(['SEL', 'BUY'][is_buy], ret))
        return ret

    def is_able_to_trade(self, is_buy):
        can_trade = False

        # macd_indicator
        can_trade = self.apply_macd_indicator(is_buy)

        # price_indicator
        can_trade |= self.apply_price_indicator(is_buy)

        # safe guard
        can_trade &= self.apply_safe_guard(is_buy)

        return can_trade

    def is_able_to_buy(self):
        return self.is_able_to_trade(is_buy = True)

    def is_able_to_sell(self):
        return self.is_able_to_trade(is_buy = False)

        
