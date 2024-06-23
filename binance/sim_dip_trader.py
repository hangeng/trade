import os
import pickle
import statistics
from lib import log
from lib import misc
from lib import kline
import matplotlib.pyplot as plt

logging = log.TraceLogging("./data/sim_dip_trader_log.txt")

class TracingCtrl:
    def __init__(self):
        self.verbose = True

    def disable_verbose(self):
        self.verbose = False

    def enable_verbose(self):
        self.verbose = True

    def get_verbose(self):
        return self.verbose

tracing_ctrl = TracingCtrl()


kline_file_cfgs = \
{
    "BTC": 
    {
        2017: "./klines/btcusdt_klines_2017-08-17_12_00_00_to_2017-12-31_07_00_00.pkl",
        2018: "./klines/btcusdt_klines_2018-01-01_07_00_00_to_2018-12-31_07_00_00.pkl",
        2019: "./klines/btcusdt_klines_2019-01-01_07_00_00_to_2019-12-31_07_00_00.pkl",
        2020: "./klines/btcusdt_klines_2020-01-01_07_00_00_to_2020-12-31_07_00_00.pkl",
        2021: "./klines/btcusdt_klines_2021-01-01_07_00_00_to_2021-12-31_07_00_00.pkl",
        2022: "./klines/btcusdt_klines_2022-01-01_07_00_00_to_2022-03-26_08_00_00.pkl",
    },
    "ETH":
    {
        2017: "./klines/ethusdt_klines_2017-08-17_12_00_00_to_2017-12-31_07_00_00.pkl",
        2018: "./klines/ethusdt_klines_2018-01-01_07_00_00_to_2018-12-31_07_00_00.pkl",
        2019: "./klines/ethusdt_klines_2019-01-01_07_00_00_to_2019-12-31_07_00_00.pkl",
        2020: "./klines/ethusdt_klines_2020-01-01_07_00_00_to_2020-12-31_07_00_00.pkl",
        2021: "./klines/ethusdt_klines_2021-01-01_07_00_00_to_2021-12-31_07_00_00.pkl",
        2022: "./klines/ethusdt_klines_2022-01-01_07_00_00_to_2022-03-26_08_00_00.pkl"
    }
}

trading_pairs_config = \
{
    "BTC": 
    {
        "kline_file_name":   None,
        "stop_loss":         0.50,
        "stop_profit_1hr":   1.015,
        "stop_profit_4hr":   1.02,
        "stop_profit_12hr":  1.05,
        "stop_profit_24hr":  1.05,
        "buy_dip_1hr":       0.9705,
        #  "buy_dip_1hr":       0.0,
        "buy_dip_4hr":       0.00,
        "buy_dip_12hr":      0.85,
        "buy_dip_24hr":      0.75,
        "name_TBD":          0.94,
        "stop_trading_days_after_fail"    : 7,
    },
    "ETH": 
    {
        "kline_file_name":   None,
        "stop_loss":         0.50,
        "stop_profit_1hr":   1.015,
        "stop_profit_4hr":   1.02,
        "stop_profit_12hr":  1.05,
        "stop_profit_24hr":  1.05,
        "buy_dip_1hr":       0.9705,
        #  "buy_dip_1hr":       0.0,
        "buy_dip_4hr":       0.00,
        "buy_dip_12hr":      0.80,
        "buy_dip_24hr":      0.70,
        "name_TBD":          0.94,
        "stop_trading_days_after_fail"    : 7,
    }
}



class StatisticsRecord:
    def __init__(self):
        self.high_24hr = 0
        self.high_12hr = 0
        self.high_8hr = 0
        self.high_4hr = 0
        self.high_1hr = 0
        self.high_15min = 0
        self.high_30min = 0

    def __str__(self):
        msg = "high_24: {} high_12: {} high_8: {} high_4: {} high_1: {} high_15min: {} high_30min: {}".format(int(self.high_24hr), int(self.high_12hr), int(self.high_8hr), int(self.high_4hr), int(self.high_1hr), int(self.high_15min), int(self.high_30min))
        return msg

class CfgsInterator():
    def __init__(self, cfgs):
        self.cfgs = cfgs
        self.index = 0

    def next(self):
        self.index += 1
        overflowed = False
        if self.index >= len(self.cfgs):
            self.index = 0
            overflowed = True

        return overflowed

    def get_current_cfg(self):
        return self.cfgs[self.index]

class Enumerator():
    def __init__(self, cfgs_iterator_array):
        self.cfgs_iterator_array = cfgs_iterator_array

    def next(self):
        level = len(self.cfgs_iterator_array) - 1

        overflowed = False
        while level >= 0:
            cfgs_interator = self.cfgs_iterator_array[level]
            if cfgs_interator.next():
                level -= 1
            else:
                break

        if level < 0:
            overflowed = True

        return overflowed

class TradingStatistics:
    def __init__(self):
        self.tx_cnt = 0
        self.fail_cnt = 0

        self.buy_1hr_succeed_cnt = 0
        self.buy_1hr_fail_cnt = 0
        self.buy_4hr_succeed_cnt = 0
        self.buy_4hr_fail_cnt = 0
        self.buy_12hr_succeed_cnt = 0
        self.buy_12hr_fail_cnt = 0
        self.buy_24hr_succeed_cnt = 0
        self.buy_24hr_fail_cnt = 0


class TradingPair:
    BUY_TYPE_1HR_BUY  = 0
    BUY_TYPE_4HR_BUY  = 1
    BUY_TYPE_12HR_BUY = 2
    BUY_TYPE_24HR_BUY = 3

    def __init__(self, symbol, kline_file_name):
        self.symbol = symbol
        self.kline_file_name = kline_file_name
        self.stats = TradingStatistics()
        with open(kline_file_name, "rb") as fp:
            self.klines = pickle.load(fp)
        self.get_statistics_summary()
        self.open_prices = []

        self.dip_percentage_1hr  = []
        self.dip_percentage_12hr = []
        for i, _ in enumerate(self.klines):
            candle_stick = kline.CandleStick(_)
            self.open_prices.append(candle_stick.get_open_price())
            if self.statistics_summary_list[i].high_1hr != 0:
                self.dip_percentage_1hr.append(candle_stick.get_close_price()/self.statistics_summary_list[i].high_1hr*100)
            else:
                self.dip_percentage_1hr.append(0)

            if self.statistics_summary_list[i].high_12hr != 0:
                self.dip_percentage_12hr.append(candle_stick.get_close_price()/self.statistics_summary_list[i].high_12hr*100)
            else:
                self.dip_percentage_12hr.append(0)


    def get_timestamp(self, min_tick):
        return kline.CandleStick(self.klines[min_tick]).get_open_time()

    def get_timestamp_str(self, min_tick):
        return kline.CandleStick(self.klines[min_tick]).get_open_time_str()

    def get_current_price(self, min_tick):
        return kline.CandleStick(self.klines[min_tick]).get_close_price()

    def get_start_timestamp(self):
        return kline.CandleStick(self.klines[0]).get_open_time()

    def get_min_ticks(self):
        return len(self.klines)


    def get_statistics_summary(self):
        self.statistics_summary_list = []
        base_name = self.kline_file_name.split('/')[-1]
        self.statistics_summary_file = "./data/{}_statistics_summary_file".format(base_name)
        if os.path.exists(self.statistics_summary_file):
            with open(self.statistics_summary_file, 'rb') as fp:
                self.statistics_summary_list = pickle.load(fp)
        else:
            last_percentage = 0
            for min_tick in range(len(self.klines)):
                cur_percentage = int(min_tick * 100 / len(self.klines))
                if last_percentage != cur_percentage:
                    logging.log_msg(str(cur_percentage))
                    last_percentage = cur_percentage
                self.update_summary(min_tick)
            with open(self.statistics_summary_file, 'wb') as fp:
                pickle.dump(self.statistics_summary_list, fp)

    def update_summary(self, min_tick):
        mins_per_15min  = 15
        mins_per_30min  = 30
        mins_per_1hr    = 60
        mins_per_4hr    = 60*4
        mins_per_8hr    = 60*8
        mins_per_12hr   = 60*12
        mins_per_24hr   = 60*24
        highest_price   = 0

        record = StatisticsRecord()
        if min_tick < mins_per_24hr:
            self.statistics_summary_list.append(record)
            return

        for index in range(mins_per_24hr):
            candle_stick = kline.CandleStick(self.klines[min_tick-index])
            if highest_price < candle_stick.get_high_price():
                highest_price = candle_stick.get_high_price()

            if index < mins_per_15min:
                record.high_15min = highest_price
            elif index < mins_per_30min:
                record.high_30min = highest_price
            elif index < mins_per_1hr:
                record.high_1hr = highest_price
            elif index < mins_per_4hr:
                record.high_4hr = highest_price
            elif index < mins_per_8hr:
                record.high_8hr = highest_price
            elif index < mins_per_12hr:
                record.high_12hr = highest_price
            elif index < mins_per_24hr:
                record.high_24hr = highest_price

        self.statistics_summary_list.append(record)

    def eval_buy(self, min_tick):
        summary_record = self.statistics_summary_list[min_tick]
        current_stick = kline.CandleStick(self.klines[min_tick])

        buy_dip_1hr = trading_pairs_config[self.symbol]['buy_dip_1hr'] 
        buy_dip_4hr = trading_pairs_config[self.symbol]['buy_dip_4hr'] 
        buy_dip_12hr = trading_pairs_config[self.symbol]['buy_dip_12hr'] 
        buy_dip_24hr = trading_pairs_config[self.symbol]['buy_dip_24hr'] 
        name_TBD = trading_pairs_config[self.symbol]['name_TBD'] 

        self.buy_price = None
        open_price = current_stick.get_open_price()

        if summary_record.high_1hr > 0 and open_price <= summary_record.high_1hr * buy_dip_1hr \
                and summary_record.high_12hr > 0 and (open_price >= summary_record.high_12hr * name_TBD):

            self.buy_price = summary_record.high_1hr * buy_dip_1hr
            self.stop_profit_price = self.buy_price * trading_pairs_config[self.symbol]['stop_profit_1hr']
            self.stop_loss_price = self.buy_price * trading_pairs_config[self.symbol]['stop_loss']
            self.buy_type = self.BUY_TYPE_1HR_BUY
            self.buy_time = current_stick.get_open_time()

        elif summary_record.high_4hr > 0 and open_price <= summary_record.high_4hr * buy_dip_4hr:
            self.buy_price = summary_record.high_4hr*buy_dip_4hr
            self.stop_profit_price = self.buy_price * trading_pairs_config[self.symbol]['stop_profit_4hr']
            self.stop_loss_price = self.buy_price * trading_pairs_config[self.symbol]['stop_loss']
            self.buy_type = self.BUY_TYPE_4HR_BUY
            self.buy_time = current_stick.get_open_time()



        elif summary_record.high_12hr > 0 and open_price <= summary_record.high_12hr * buy_dip_12hr:
            self.buy_price = summary_record.high_12hr*buy_dip_12hr
            self.stop_profit_price = self.buy_price * trading_pairs_config[self.symbol]['stop_profit_12hr']
            self.stop_loss_price = self.buy_price * trading_pairs_config[self.symbol]['stop_loss']
            self.buy_type = self.BUY_TYPE_12HR_BUY
            self.buy_time = current_stick.get_open_time()


        elif summary_record.high_24hr > 0 and open_price <= summary_record.high_24hr * buy_dip_24hr:
            self.buy_price = summary_record.high_24hr*buy_dip_24hr
            self.stop_profit_price = self.buy_price * trading_pairs_config[self.symbol]['stop_profit_24hr']
            self.stop_loss_price = self.buy_price * trading_pairs_config[self.symbol]['stop_loss']
            self.buy_type = self.BUY_TYPE_24HR_BUY
            self.buy_time = current_stick.get_open_time()


        if self.buy_price != None:
            if tracing_ctrl.get_verbose():
                logging.log_msg("-"*40)
                logging.log_msg("{}high_24hr:  {} ({:.2f}%)".format("*" if self.buy_type == self.BUY_TYPE_24HR_BUY else " ", int(summary_record.high_24hr), 100.0*open_price/summary_record.high_24hr))
                logging.log_msg("{}high_12hr:  {} ({:.2f}%)".format("*" if self.buy_type == self.BUY_TYPE_12HR_BUY else " ", int(summary_record.high_12hr), 100.0*open_price/summary_record.high_12hr))
                logging.log_msg("{}high_4hr:   {} ({:.2f}%)".format("*" if self.buy_type == self.BUY_TYPE_4HR_BUY else " ", int(summary_record.high_4hr), 100.0*open_price/summary_record.high_4hr))
                logging.log_msg("{}high_1hr:   {} ({:.2f}%)".format("*" if self.buy_type == self.BUY_TYPE_1HR_BUY else " ", int(summary_record.high_1hr), 100.0*open_price/summary_record.high_1hr))
                logging.log_msg(" open_price: {}".format(int(open_price)))
                logging.log_msg(" buy_price:  {}".format(int(self.buy_price)))
            self.stats.tx_cnt += 1
            return True
        else:
            return False

    def eval_sel(self, min_tick):
        summary_record = self.statistics_summary_list[min_tick]
        current_stick = kline.CandleStick(self.klines[min_tick])

        holding_hours = (current_stick.get_open_time() - self.buy_time).total_seconds()/3600

        self.sell_price = None
        tx_failed = False
        if current_stick.get_close_price() >= self.stop_profit_price:
            self.sell_price = self.stop_profit_price
            if self.buy_type == self.BUY_TYPE_1HR_BUY:
                self.stats.buy_1hr_succeed_cnt += 1
            elif self.buy_type == self.BUY_TYPE_4HR_BUY:
                self.stats.buy_4hr_succeed_cnt += 1
            elif self.buy_type == self.BUY_TYPE_12HR_BUY:
                self.stats.buy_12hr_succeed_cnt += 1
            elif self.buy_type == self.BUY_TYPE_24HR_BUY:
                self.stats.buy_24hr_succeed_cnt += 1

        elif current_stick.get_close_price() <= self.stop_loss_price:
            self.sell_price = self.stop_loss_price
            if self.buy_type == self.BUY_TYPE_1HR_BUY:
                self.stats.buy_1hr_fail_cnt += 1
            elif self.buy_type == self.BUY_TYPE_4HR_BUY:
                self.stats.buy_4hr_fail_cnt += 1
            elif self.buy_type == self.BUY_TYPE_12HR_BUY:
                self.stats.buy_12hr_fail_cnt += 1
            elif self.buy_type == self.BUY_TYPE_24HR_BUY:
                self.stats.buy_24hr_fail_cnt += 1
        
            if tracing_ctrl.get_verbose():
                logging.log_msg("-------fail----------")

            self.stats.fail_cnt += 1
            tx_failed = True
        #  else:
            #  if self.buy_type == self.BUY_TYPE_1HR_BUY and holding_hours > 24*14.0:
                #  self.sell_price = current_stick.get_close_price()
                #  self.stats.buy_1hr_fail_cnt += 1
                #  self.stats.fail_cnt += 1
                #  tx_failed = True
        
        return (self.sell_price != None, tx_failed)



class TradingAccount:
    def __init__(self):
        self.reset()

    
    def reset(self):

        self.current_stick = None
        self.usdt = 10000
        self.dcoin = 0
        self.profit = 1.0

        self.symbol_in_trading = None

        self.now_str = None
        self.now_timestamp = None
        self.fiat_history =[]
        self.frozen_until_to = 0

        self.holding_time_x = []
        self.holding_time_y = []
        self.trading_cnt_histogram = [0]*12
        self.month_start_fiat = [0]*12
        self.month_profit = [0]*12
        self.trading_pairs = {}

        self.symbols_to_monitor = []


    def add_trading_pair(self, symbol, kline_file_name):
        trading_pair = TradingPair(symbol, kline_file_name)
        self.trading_pairs[symbol] = trading_pair
        self.symbols_to_monitor.append(symbol)


    def eval(self):
        if self.min_tick <= self.frozen_until_to:
            return

        if self.symbol_in_trading is None:
            if self.now_timestamp.month in [3, 5, 9]:
                return 
            for symbol in self.symbols_to_monitor:
                if self.trading_pairs[symbol].eval_buy(self.min_tick):
                    self.exec_buy(symbol)
                    break
        else:
            symbol_in_trading = self.symbol_in_trading
            to_sell, tx_failed = self.trading_pairs[self.symbol_in_trading].eval_sel(self.min_tick)
            if to_sell:
                self.exec_sell(self.symbol_in_trading)
                self.symbol_in_trading = None

            if tx_failed:
                self.frozen_until_to = self.min_tick + trading_pairs_config[symbol_in_trading]['stop_trading_days_after_fail']*24*60



    def exec_buy(self, symbol):
        buy_price = self.trading_pairs[symbol].buy_price
        self.dcoin = self.usdt / buy_price
        self.usdt = 0
        self.buy_time = self.now_timestamp
        self.symbol_in_trading = symbol
        if tracing_ctrl.get_verbose():
            logging.log_msg("{}: EXEC: BUY {} {:.4f} @ {:.4f}".format(self.now_str, symbol, self.dcoin, buy_price))

    def exec_sell(self, symbol):
        commission_fees = 0.000
        sell_price = self.trading_pairs[symbol].sell_price
        buy_price = self.trading_pairs[symbol].buy_price

        dcoin_to_sell = self.dcoin
        self.usdt = self.dcoin * sell_price * (1 - commission_fees)
        self.dcoin = 0
        self.holding_time_x.append((self.now_timestamp - self.trading_pairs[symbol].get_start_timestamp()).total_seconds())
        holding_days = (self.now_timestamp - self.buy_time).total_seconds()/3600/24
        self.holding_time_y.append(holding_days)

        self.trading_cnt_histogram[self.trading_pairs[symbol].get_timestamp(self.min_tick).month-1] += 1
        if tracing_ctrl.get_verbose():
            logging.log_msg("{}: EXEC: SEL {} {:.4f} @ {:.4f} : {:.4f}".format(self.now_str, symbol, dcoin_to_sell, sell_price, dcoin_to_sell * sell_price))

    def clock_tick(self, min_tick):
        self.min_tick = min_tick
        self.now_timestamp = self.trading_pairs[self.symbols_to_monitor[0]].get_timestamp(min_tick)
        self.now_str = self.trading_pairs[self.symbols_to_monitor[0]].get_timestamp_str(min_tick)
        self.eval()
        self.update_fiat()

    def update_fiat(self):
        dcoin_asset = 0
        if self.symbol_in_trading != None:
            dcoin_asset = self.dcoin * self.trading_pairs[self.symbol_in_trading].get_current_price(self.min_tick)
        fiat_asset = self.usdt + dcoin_asset
        self.fiat_history.append(fiat_asset)

        month = self.now_timestamp.month - 1
        if self.month_start_fiat[month] == 0:
            self.month_start_fiat[month] = fiat_asset
        self.month_profit[month] = (fiat_asset - self.month_start_fiat[month]) * 100.0 / self.month_start_fiat[month]

    def get_tx_count(self):
        tx_cnt = 0
        for symbol in self.symbols_to_monitor:
            tx_cnt += self.trading_pairs[symbol].stats.tx_cnt
        return tx_cnt

    def get_tx_fail_count(self):
        tx_fail_cnt = 0
        for symbol in self.symbols_to_monitor:
            tx_fail_cnt += self.trading_pairs[symbol].stats.fail_cnt
        return tx_fail_cnt


    def show_cfg(self):
        logging.log_msg("configure:")
        for symbol in self.symbols_to_monitor:
            logging.log_msg (symbol)
            logging.log_msg("    stop_loss:                       {:.4f}".format(trading_pairs_config[symbol]['stop_loss']))
            logging.log_msg("    stop_profit_1hr:                 {:.4f}".format(trading_pairs_config[symbol]['stop_profit_1hr']))
            logging.log_msg("    stop_profit_4hr:                 {:.4f}".format(trading_pairs_config[symbol]['stop_profit_4hr']))
            logging.log_msg("    stop_profit_12hr:                {:.4f}".format(trading_pairs_config[symbol]['stop_profit_12hr']))
            logging.log_msg("    stop_profit_24hr:                {:.4f}".format(trading_pairs_config[symbol]['stop_profit_24hr']))
            logging.log_msg("    buy_dip_1hr:                     {:.4f}".format(trading_pairs_config[symbol]['buy_dip_1hr']))
            logging.log_msg("    buy_dip_4hr:                     {:.4f}".format(trading_pairs_config[symbol]['buy_dip_4hr']))
            logging.log_msg("    buy_dip_12hr:                    {:.4f}".format(trading_pairs_config[symbol]['buy_dip_12hr']))
            logging.log_msg("    buy_dip_24hr:                    {:.4f}".format(trading_pairs_config[symbol]['buy_dip_24hr']))
            logging.log_msg("    stop_trading_days_after_fail:    {}".format(trading_pairs_config[symbol]['stop_trading_days_after_fail']))

    def show_result(self):
        logging.log_msg("result:")
        logging.log_msg("    start_time:           {}".format(self.start_time))
        logging.log_msg("    end_time:             {}".format(self.end_time))
        logging.log_msg("    profit %:             {:.2f}%".format((self.fiat_history[-1] - 10000)*100.0/10000))
        logging.log_msg("    tx cnt:               {}".format(self.get_tx_count()))
        logging.log_msg("    fail cnt:             {}".format(self.get_tx_fail_count()))

        for symbol in self.symbols_to_monitor:
            logging.log_msg (symbol)
            logging.log_msg("    1hr_succeed_cnt:  {}".format(self.trading_pairs[symbol].stats.buy_1hr_succeed_cnt))
            logging.log_msg("    1hr_fail_cnt:     {}".format(self.trading_pairs[symbol].stats.buy_1hr_fail_cnt))
            logging.log_msg("    4hr_succeed_cnt:  {}".format(self.trading_pairs[symbol].stats.buy_4hr_succeed_cnt))
            logging.log_msg("    4hr_fail_cnt:     {}".format(self.trading_pairs[symbol].stats.buy_4hr_fail_cnt))
            logging.log_msg("    12hr_succeed_cnt: {}".format(self.trading_pairs[symbol].stats.buy_12hr_succeed_cnt))
            logging.log_msg("    12hr_fail_cnt:    {}".format(self.trading_pairs[symbol].stats.buy_12hr_fail_cnt))
            logging.log_msg("    24hr_succeed_cnt: {}".format(self.trading_pairs[symbol].stats.buy_24hr_succeed_cnt))
            logging.log_msg("    24hr_fail_cnt:    {}".format(self.trading_pairs[symbol].stats.buy_24hr_fail_cnt))

    def show_histogram(self):
        logging.log_msg("trading histogram")

        logging.log_msg("Mon Tx  Profit(%)")
        for i in range(12):
            #  logging.log_msg("{:2d}: {:2d}, {:.2f}".format(i+1, self.trading_cnt_histogram[i], self.month_profit[i]))
            logging.log_msg("{:2d}, {:.2f}".format(self.trading_cnt_histogram[i], self.month_profit[i]))

        
        holding_time_sep = [1.0/6, 1, 2, 7, 14, 30, 60]
        holding_time_cnt = [0,     0, 0, 0, 0,  0,   0]

        for holding_time in self.holding_time_y:
            for i, sep in enumerate(holding_time_sep):
                if holding_time <= sep:
                    holding_time_cnt[i] += 1
                    break

        logging.log_msg("avg holding time {:.2f} days".format(statistics.mean(self.holding_time_y)))
        for sep, cnt in zip(holding_time_sep, holding_time_cnt):
            logging.log_msg("<= {:.2f}: {}".format(sep, cnt))


    def show(self):
        self.show_cfg()
        self.show_result()
        self.show_histogram()

    def plt_asset(self):
        ax1 = plt.subplot(2, 1, 1)
        eth_price_scale = 10
        for symbol in self.symbols_to_monitor:
            if symbol == "ETH":
                open_prices = [x*eth_price_scale for x in self.trading_pairs[symbol].open_prices]
            else:
                open_prices = self.trading_pairs[symbol].open_prices
            ax1.plot(open_prices,  label='open price', alpha = 0.35)

        ax2 = plt.subplot(2, 1, 2, sharex=ax1)
        ax2.plot(self.fiat_history, label='fiat', color = 'red')

        #  symbol = self.symbols_to_monitor[0]
        #  dip_percentage_1hr = self.trading_pairs[symbol].dip_percentage_1hr
        #  ax2.plot(dip_percentage_1hr, label='dip 1hr avg {}'.format(statistics.mean(dip_percentage_1hr)), color = 'red', marker='o')

        #  dip_percentage_12hr = self.trading_pairs[symbol].dip_percentage_12hr
        #  ax2.plot(dip_percentage_12hr, label='dip 12hr avg {}'.format(statistics.mean(dip_percentage_12hr)), color = 'blue', marker='x')
        plt.legend()
        plt.show()

    def monitor(self):
        symbol = self.symbols_to_monitor[0]
        min_ticks = min([self.trading_pairs[symbol].get_min_ticks() for symbol in self.symbols_to_monitor])

        start_tick = 60*24*0
        end_tick   = min_ticks

        for i in range(start_tick, end_tick):
            self.clock_tick(i)

        self.start_time = self.trading_pairs[symbol].get_timestamp_str(start_tick)
        self.end_time = self.trading_pairs[symbol].get_timestamp_str(end_tick-1)

        self.profit = (self.fiat_history[-1] - 10000)/10000



def run_single_cfg():
    account = TradingAccount()
    #  tracing_ctrl.disable_verbose()

    result_summary = \
    {
        2017: 0,
        2018: 0,
        2019: 0,
        2020: 0,
        2021: 0,
        2022: 0
    }

    overall_profit = 1.0
    symbols_to_monitor = ["BTC", "ETH"]
    #  symbols_to_monitor = ["BTC"]
    #  for year in [2017, 2018, 2019, 2020, 2021]:
    for year in [2022]:
        account.reset()
        for symbol in symbols_to_monitor:
            account.add_trading_pair(symbol, kline_file_cfgs[symbol][year])
        account.monitor()
        account.show()
        account.plt_asset()
        result_summary[year] = account.profit
        overall_profit *= (1 + account.profit)

    logging.log_msg("Summary Table")
    logging.log_msg("2017    2018    2019    2020    2021    2022    overall")
    logging.log_msg("{:<8.2f}{:<8.2f}{:<8.2f}{:<8.2f}{:<8.2f}{:<8.2f}{:<8.2f}".format(result_summary[2017]*100, 
                                                                              result_summary[2018]*100, 
                                                                              result_summary[2019]*100, 
                                                                              result_summary[2020]*100, 
                                                                              result_summary[2021]*100,
                                                                              result_summary[2022]*100,
                                                                              (overall_profit - 1)*100))







def enumerate_cfgs():
    account = TradingAccount()
    tracing_ctrl.disable_verbose()


    #  btc_buy_1hr_cfgs = CfgsInterator([0.97, 0.9705, 0.9706])
    #  eth_buy_1hr_cfgs = CfgsInterator([0.97, 0.9705, 0.9706])

    btc_buy_1hr_cfgs = CfgsInterator([0.9706])
    eth_buy_1hr_cfgs = CfgsInterator([0.9706])

    btc_buy_12hr_cfgs = CfgsInterator([0.85])
    eth_buy_12hr_cfgs = CfgsInterator([0.80])

    btc_buy_24hr_cfgs = CfgsInterator([0.75])
    eth_buy_24hr_cfgs = CfgsInterator([0.70])

    #  btc_stop_1hr_profit_cfgs = CfgsInterator([1.014, 1.015, 1.016, 1.017])
    #  eth_stop_1hr_profit_cfgs = CfgsInterator([1.014, 1.015, 1.016, 1.017])
    btc_stop_1hr_profit_cfgs = CfgsInterator([1.015])
    eth_stop_1hr_profit_cfgs = CfgsInterator([1.015])
    
    btc_stop_12hr_profit_cfgs = CfgsInterator([1.05])
    eth_stop_12hr_profit_cfgs = CfgsInterator([1.05])

    btc_stop_24hr_profit_cfgs = CfgsInterator([1.05])
    eth_stop_24hr_profit_cfgs = CfgsInterator([1.05])


    symbols_to_monitor = ["BTC", "ETH"]
    years_to_loopover = [2017,2018,2019,2020,2021, 2022]

    cfgs_iterator_array = \
    [
            btc_buy_1hr_cfgs,
            eth_buy_1hr_cfgs,
            btc_buy_12hr_cfgs,
            eth_buy_12hr_cfgs,
            btc_buy_24hr_cfgs,
            eth_buy_24hr_cfgs,
            btc_stop_1hr_profit_cfgs,
            eth_stop_1hr_profit_cfgs,
            btc_stop_12hr_profit_cfgs,
            eth_stop_12hr_profit_cfgs,
            btc_stop_24hr_profit_cfgs,
            eth_stop_24hr_profit_cfgs
    ]

    cfgs_enumerator = Enumerator(cfgs_iterator_array)

    config_id = 0
    result_summary = {}

    while True:
        logging.log_msg("configure ID: {}".format(config_id))
        overall_profit = 1.0
        result_summary[config_id] = []
        for year in years_to_loopover:
            account.reset()
            for symbol in symbols_to_monitor:
                if symbol == "BTC":
                    trading_pairs_config[symbol]['buy_dip_1hr'] = btc_buy_1hr_cfgs.get_current_cfg()
                    trading_pairs_config[symbol]['buy_dip_12hr'] = btc_buy_12hr_cfgs.get_current_cfg()
                    trading_pairs_config[symbol]['buy_dip_24hr'] = btc_buy_24hr_cfgs.get_current_cfg()
                    trading_pairs_config[symbol]['stop_profit_1hr'] = btc_stop_1hr_profit_cfgs.get_current_cfg()
                    trading_pairs_config[symbol]['stop_profit_12hr'] = btc_stop_12hr_profit_cfgs.get_current_cfg()
                    trading_pairs_config[symbol]['stop_profit_24hr'] = btc_stop_24hr_profit_cfgs.get_current_cfg()
                elif symbol == "ETH":
                    trading_pairs_config[symbol]['buy_dip_1hr'] = eth_buy_1hr_cfgs.get_current_cfg()
                    trading_pairs_config[symbol]['buy_dip_12hr'] = eth_buy_12hr_cfgs.get_current_cfg()
                    trading_pairs_config[symbol]['buy_dip_24hr'] = eth_buy_24hr_cfgs.get_current_cfg()
                    trading_pairs_config[symbol]['stop_profit_1hr'] = eth_stop_1hr_profit_cfgs.get_current_cfg()
                    trading_pairs_config[symbol]['stop_profit_12hr'] = eth_stop_12hr_profit_cfgs.get_current_cfg()
                    trading_pairs_config[symbol]['stop_profit_24hr'] = eth_stop_24hr_profit_cfgs.get_current_cfg()
                kline_file = kline_file_cfgs[symbol][year]
                account.add_trading_pair(symbol, kline_file)
            account.monitor()
            account.show()
            result_summary[config_id].append(account.profit)
            overall_profit *= (1 + account.profit)
        logging.log_msg ("===> overall profit: {:.2f}%".format(overall_profit*100))
        result_summary[config_id].append(overall_profit)
        config_id += 1

        if cfgs_enumerator.next():
            break

    logging.log_msg("Summary Table")
    logging.log_msg("ID      2017    2018    2019    2020    2021    2022    overall")
    for id in range(config_id):
        logging.log_msg("{:<8d}{:<8.2f}{:<8.2f}{:<8.2f}{:<8.2f}{:<8.2f}{:<8.2f}{:<8.2f}".format(id, 
                                                                                    result_summary[id][0]*100, 
                                                                                    result_summary[id][1]*100, 
                                                                                    result_summary[id][2]*100, 
                                                                                    result_summary[id][3]*100, 
                                                                                    result_summary[id][4]*100,
                                                                                    result_summary[id][5]*100,
                                                                                    result_summary[id][6]*100))


if __name__ == "__main__":
    #  run_single_cfg()
    enumerate_cfgs()


