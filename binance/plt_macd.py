import pickle
import datetime
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

plt.style.use('fivethirtyeight')

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


class MACD:
    def __init__(self, klines):
        self.klines = klines
        self.macd_df = pd.DataFrame()

    def generate_buy_sell(self):
        sigPriceBuy = []
        sigPriceSell = []
        flag = -1
        for i in range(0, len(self.macd_df)):
            #if MACD > signal line  then buy else sell
            if self.macd_df['MACD'][i] > self.macd_df['signal'][i]:
                if flag != 1:
                    sigPriceBuy.append(self.macd_df['close'][i])
                    sigPriceSell.append(np.nan)
                    flag = 1
                else:
                    sigPriceBuy.append(np.nan)
                    sigPriceSell.append(np.nan)
            elif self.macd_df['MACD'][i] < self.macd_df['signal'][i]: 
                if flag != 0:
                    sigPriceSell.append(self.macd_df['close'][i])
                    sigPriceBuy.append(np.nan)
                    flag = 0
                else:
                    sigPriceBuy.append(np.nan)
                    sigPriceSell.append(np.nan)
            else: #Handling nan values
                sigPriceBuy.append(np.nan)
                sigPriceSell.append(np.nan)
        self.macd_df['buy'] = sigPriceBuy
        self.macd_df['sell'] = sigPriceSell

        print (str(self.macd_df))


        #  self.macd_df.set_index(pd.DatetimeIndex(self.macd_df['date'].values))


        # Visually Show The Stock buy and sell signals
        # Create the title 
        title = 'Close Price History Buy / Sell Signals   '
        #Get the stocks
        my_stocks = self.macd_df
          
        #Create and plot the graph
        ax1 = plt.subplot(2, 1, 1)

        #  ax1.figure(figsize=(12.2,4.5)) #width = 12.2in, height = 4.5
        ax1.scatter(my_stocks.index, my_stocks['buy'], color = 'green', label='Buy Signal', marker = '^', alpha = 1)
        ax1.scatter(my_stocks.index, my_stocks['sell'], color = 'red', label='Sell Signal', marker = 'v', alpha = 1)
        ax1.plot( my_stocks['close'],  label='Close Price', alpha = 0.35)#plt.plot( X-Axis , Y-Axis, line_width, alpha_for_blending,  label)


        ax2 = plt.subplot(2, 1, 2, sharex=ax1)
        ax2.plot(my_stocks['MACD'], label='MACD', color = 'red')
        ax2.plot(my_stocks['signal'], label='Signal Line', color='blue')


        #  plt.xticks(rotation=45)
        plt.title(title)
        plt.xlabel('Date',fontsize=18)
        plt.ylabel('Close Price USD ($)',fontsize=18)
        plt.legend( loc='upper left')
        plt.show()


    def generate_macd(self):
        prices = []
        date = []
        cnt = 0
        for kline in self.klines:
            cnt += 1
            #  if cnt > 2000:
                #  break
            candle = Candle(kline)
            prices.append(candle.get_close_price())
            date.append(candle.get_open_time_str())

        #  plt.figure(figsize=(12.2, 4.5))
        #  plt.plot(prices,  label='Close') #plt.plot( X-Axis , Y-Axis, line_width, alpha_for_blending,  label)
        #  plt.xticks(rotation=45) 
        #  plt.title("close price")
        #  plt.xlabel('Date',fontsize=18)
        #  plt.ylabel('Price USD ($)',fontsize=18)
        #  plt.show()

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
        macd = [x * 10 ** 6 for x in macd]
        signal = [x * 10 ** 6 for x in signal]
        

        diff = []
        for i in range(len(macd)):
            diff.append(abs(macd[i] - signal[i]))

        self.macd_df['date'] = date
        self.macd_df['MACD'] = macd
        self.macd_df['signal'] = signal
        self.macd_df['close'] = prices

        print (macd)
        print (signal)

        print (self.macd_df)

        plt.figure(figsize=(12.2,4.5)) #width = 12.2in, height = 4.5

        ax1 = plt.subplot(3, 1, 1)
        ax1.plot(prices[200:], label='price', color='black')

        ax2 = plt.subplot(3, 1, 2, sharex=ax1)
        ax2.plot(macd[200:], label='MACD', color = 'red')
        ax2.plot(signal[200:], label='Signal Line', color='blue')

        ax3 = plt.subplot(3, 1, 3, sharex=ax1)
        ax3.plot(diff[200:], label='diff', color = 'red')

        plt.xticks(rotation=45)
        plt.legend(loc='upper left')
        plt.show()

        self.generate_buy_sell()



if __name__ == "__main__":
    with open("./klines/btcusdt_klines.pkl", "rb") as tf:
        klines = pickle.load(tf)

    macd = MACD(klines)
    macd.generate_macd()
