import pickle
from binance.client import Client
from lib import kline

api_key='U4D1lrVeSRgtE2nzWGv8hERR4udZ70RXMyudnbzE1DDa8jAnqix2h8IIMtzQSfv1'
api_secret='biwajUrGzz6q9O0wDVoS0Y195J4eqcrPBh9caViH3KYFmSxoLbxLTTCnPsUhG0TO'


SYMBOL = "BTCBUSD"

def dump_klines():
    client = Client(api_key, api_secret)
    #  kl = client.get_historical_klines(SYMBOL, Client.KLINE_INTERVAL_15MINUTE , "1 day ago UTC")
    #  kl = client.get_historical_klines(SYMBOL, Client.KLINE_INTERVAL_15MINUTE , "15 May, 2021")
    #  kl = client.get_historical_klines(SYMBOL, Client.KLINE_INTERVAL_15MINUTE , "1 Feb, 2021")
    kl = client.get_historical_klines(SYMBOL, Client.KLINE_INTERVAL_1SECOND , "1 Jan, 2022")
    #  kl = client.get_historical_klines(SYMBOL, Client.KLINE_INTERVAL_1MINUTE , "1 Jan, 2019", "31 Dec, 2019")
    #  kl = client.get_historical_klines(SYMBOL, Client.KLINE_INTERVAL_1MINUTE , "1 Jan, 2017", "31 Dec, 2017")



    start_candle_stick = kline.CandleStick(kl[0])
    end_candle_stick = kline.CandleStick(kl[-1])
    file_name = "./klines/{}_klines_{}_to_{}.pkl".format(SYMBOL.lower(), start_candle_stick.get_open_time_str(), end_candle_stick.get_open_time_str())
    file_name = file_name.replace(' ', '_')
    file_name = file_name.replace(':', '_')
    with open(file_name, "wb") as tf:
        pickle.dump(kl, tf)

if __name__ == "__main__":
    dump_klines()

