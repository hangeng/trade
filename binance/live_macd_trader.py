import pandas as pd
import math
import datetime
import time
from datetime import date
import random
from binance.client import Client

api_key=""
api_secret=""

SYMBOL="BUSDUSDT"
EPOCH_INTERVAL_IN_MINUTES = 15

MUST_SELL_PRICE = 0.9999
MUST_BUY_PRICE  = 0.9983

STOP_BUY_PRICE  = 0.9995
STOP_SELL_PRICE = 0.9983
DIFF_PRICE      = 0.0010
MACD_CEIL       = 200
MACD_FLOOR      = -150
LOG_FILE = "./macd_log.txt"

def truncate(f, n):
    return math.floor(f * 10 ** n) / 10 ** n

class Candle:
    def __init__(self, kline):
        self.kline = kline

    def get_open_time_str(self):
        d = datetime.datetime.fromtimestamp(self.kline[0]/1000)
        return d.strftime("%Y-%m-%d %H:%M:%S")

    def get_open_time(self):
        return datetime.datetime.fromtimestamp(self.kline[0]/1000)
    
    def get_open_price(self):
        return float(self.kline[1])

    def get_close_price(self):
        return float(self.kline[4])

    def get_high_price(self):
        return float(self.kline[2])
    
    def get_low_price(self):
        return float(self.kline[3])

    def get_volume(self):
        return float(self.kline[5])

    def __str__(self):
        return "{}: o/h/l/c {}/{}/{}/{}".format(self.get_open_time_str(), self.get_open_price(), self.get_high_price(), self.get_low_price(), self.get_close_price())


class TradingAccount:
    def __init__(self, client):
        self.client = client
        self.macd = None
        self.signal = None


    def get_kline_interval(self):
        if EPOCH_INTERVAL_IN_MINUTES == 15:
            return Client.KLINE_INTERVAL_15MINUTE
        elif EPOCH_INTERVAL_IN_MINUTES == 60:
            return Client.KLINE_INTERVAL_1HOUR
        else:
            assert "TBD"

    def get_balance_asset(self, asset):
        balance = self.client.get_asset_balance(asset=asset)
        return round(float(balance['free']) + float(balance['locked']), 2)

    def now(self):
        return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    def get_symbol_immediate_price(self, symbol):
        ticker_prices = self.client.get_all_tickers()
        for ticker in ticker_prices:
            if ticker['symbol'] == symbol:
                return round(float(ticker['price']), 4)

    def get_symbol_immediate_buy_price(self, symbol):
        order_book = client.get_order_book(symbol=symbol)
        return float(order_book['asks'][0][0])

    def get_symbol_immediate_sell_price(self, symbol):
        order_book = client.get_order_book(symbol=symbol)
        return float(order_book['bids'][0][0])

    def get_last_closed_order_price(self):
        orders = client.get_all_orders(symbol=SYMBOL, limit=100)
        orders.reverse()
        for order in orders:
            if order['status'] == 'FILLED':
                return float(order['price'])
        return None


    def update_macd(self):
        klines = self.client.get_historical_klines(SYMBOL, self.get_kline_interval() , "15 day ago UTC")

        #  candle = Candle(klines[-1])
        #  print (str(candle))

        prices = []
        for kline in klines:
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

    def cancel_all_open_orders(self):
        orders = self.client.get_open_orders(symbol=SYMBOL)
        for order in orders:
             result = self.client.cancel_order(symbol=SYMBOL, orderId=order['orderId'])

    def get_asset_balance(self, asset):
        balance = self.client.get_asset_balance(asset=asset)
        balance_free = truncate(float(balance['free']), 2)
        return balance_free


    def macd_indicator_signal(self, is_buy):
        self.log_msg("-"*75)
        self.log_msg("MACD_CEIL: {} MACD_FLOOR: {}".format(MACD_CEIL, MACD_FLOOR))


        df = pd.DataFrame()
        df['macd'] = self.macd[-11:]
        df['signal'] = self.signal[-11:]
        self.log_msg(str(df))

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
        for i in range(2, 12):
            if self.macd[-i] > self.signal[-i]:
                macd_vs_signal.append(1)
            elif self.macd[-i] < self.signal[-i]:
                macd_vs_signal.append(-1)
            else:
                macd_vs_signal.append(0)

        if is_buy:
            if sum(macd_vs_signal) == -10:
                return True
        else:
            if sum(macd_vs_signal) == 10:
                return True

        return False

    def refresh_price(self):
        self.immediate_buy_price = self.get_symbol_immediate_buy_price(SYMBOL) 
        self.immediate_sell_price = self.get_symbol_immediate_sell_price(SYMBOL) 
        self.last_trade_price = self.get_last_closed_order_price()

    def price_indicator_signal(self, is_buy):
        indicator = False
        self.log_msg("-"*75)
        self.log_msg("cur_BUY_price: {:.4f} cur_SEL_price: {:.4f} last_TRADE_price: {:.4f} MUST_BUY_PRICE: {:.4f} DIFF_PRICE: {:.4f}".format(self.immediate_buy_price, 
                                                                                                   self.immediate_sell_price,
                                                                                                   self.last_trade_price,
                                                                                                   MUST_BUY_PRICE,
                                                                                                   DIFF_PRICE))
        if is_buy:
            if self.immediate_buy_price <= MUST_BUY_PRICE:
                indicator = True
            if self.immediate_buy_price <= (self.last_trade_price - DIFF_PRICE):
                indicator = True
        else:
            if self.immediate_sell_price >= MUST_SELL_PRICE:
                indicator = True
            if self.immediate_sell_price >= (self.last_trade_price + DIFF_PRICE):
                indicator = True

        indicator = False

        self.log_msg("{} price_indicator_signal: {}".format(["SEL", "BUY"][is_buy], indicator))
        self.log_msg("-"*75)

        return indicator

    def safe_guard(self, is_buy):
        safe = True
        if is_buy:
            if self.immediate_buy_price >= STOP_BUY_PRICE:
                safe = False
        else:
            if self.immediate_sell_price <= STOP_SELL_PRICE:
                safe = False

        self.log_msg("{} safe_guard: STOP_BUY_PRICE {} STOP_SELL_PRICE {} safe {}".format(["SEL", "BUY"][is_buy], STOP_BUY_PRICE, STOP_SELL_PRICE, safe))
        self.log_msg("-"*75)

        return safe


    def try_to_sell(self, busd):
        trade = False

        # macd_indicator
        if self.macd_indicator_signal(is_buy=False):
            trade = True
            self.log_msg("SEL: macd_indicator_signal: True")
        else:
            self.log_msg("SEL: macd_indicator_signal: False")

        # price_indicator
        if self.price_indicator_signal(is_buy=False):
            trade = True

        # safe guard
        trade &= self.safe_guard(is_buy=False)

        if trade:
            order_price = self.immediate_sell_price
            

            order = self.client.order_limit_sell(symbol=SYMBOL, 
                                                 quantity=busd,
                                                 price=order_price)

            log_msg = "{}: EXEC: SEL {} @ {}".format(self.now(), busd, order_price)
            self.log_msg(log_msg)

    def try_to_buy(self, usdt):
        trade = False

        # macd_indicator
        if self.macd_indicator_signal(is_buy=True):
            trade = True
            self.log_msg("BUY: macd_indicator_signal: True")
        else:
            self.log_msg("BUY: macd_indicator_signal: False")

        # price_indicator
        if self.price_indicator_signal(is_buy=True):
            trade = True

        # safe guard
        trade &= self.safe_guard(is_buy=True)

        if trade:
            order_price = self.immediate_buy_price

            busd = int(usdt/order_price)

            order = self.client.order_limit_buy(symbol=SYMBOL, 
                                                quantity=busd,
                                                price=order_price)

            log_msg = "{}: EXEC: BUY {} @ {}".format(self.now(), busd, order_price)
            self.log_msg(log_msg)
            
    def check_and_trade(self):
        # cancel all open orders
        self.cancel_all_open_orders()

        # update MACD
        self.update_macd()

        # refresh price
        self.refresh_price()

        busd_free = self.get_asset_balance('BUSD')
        if busd_free >= 15:
            self.try_to_sell(busd_free)

        usdt_free = self.get_asset_balance('USDT')
        if usdt_free >= 15:
            self.try_to_buy(usdt_free)

    def log_msg(self, log_msg):
        print (log_msg)
        with open(LOG_FILE, "a") as log_fd:
            log_fd.write(log_msg)
            log_fd.write("\n")
    

    def show_account(self):
        busd_asset = self.get_balance_asset("BUSD")
        usdt_asset = self.get_balance_asset("USDT")
        price = self.get_symbol_immediate_price(SYMBOL)

        all_busd = busd_asset + usdt_asset/self.get_symbol_immediate_buy_price(SYMBOL)
        all_usdt = usdt_asset + busd_asset*self.get_symbol_immediate_sell_price(SYMBOL)

        fiat_asset = max(busd_asset+usdt_asset, all_busd, all_usdt)

        log_msg = "{}: BUSD {} USDT {} sum {:.2f} ({:.2f}$) price {:.4f}".format(self.now(), 
                                                                                 busd_asset, 
                                                                                 usdt_asset, 
                                                                                 busd_asset + usdt_asset, 
                                                                                 fiat_asset,
                                                                                 price)
        open_orders = self.client.get_open_orders(symbol=SYMBOL)
        log_msg += " ORDERS: "
        for order in open_orders:
            order_price = float(order['price'])
            orig_qty = float(order['origQty'])

            if order['side'] == 'SELL':
                order_side = 'SEL'
            else:
                order_side = 'BUY'
            log_msg += " {} {:.2f}@{:.4f}".format(order_side, orig_qty, order_price)

        self.log_msg(log_msg)


    def monitor(self):
        while True:
            try:
                self.check_and_trade()
                self.show_account()
                time.sleep(1)
            except:
                time.sleep(1)

if __name__ == "__main__":
    client = Client(api_key, api_secret)
    account = TradingAccount(client)
    account.monitor()

