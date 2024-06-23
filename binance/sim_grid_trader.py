import pickle
import datetime
from lib import log
from lib import misc
from lib import kline
import matplotlib.pyplot as plt
from lib.misc import *


logging = log.TraceLogging("./data/sim_dip_trader_log.txt")


#  grid_bot_parameters = \
#  {
    #  "lower_limit":   300,
    #  "upper_limit":   2000,
    #  "grid_cnt":      100,
    #  "start_price":   1500,
#  }
grid_bot_parameters = \
{
    "lower_limit":   16200,
    "upper_limit":   16800,
    "grid_cnt":      100,
    "start_price":   16500,
}


class Grid:
    GRID_STAT_OPEN   = 0
    GRID_STAT_CLOSED = 1

    def __init__(self):
        self.lower = None
        self.upper = None
        self.buy_price = 0
        self.state = self.GRID_STAT_CLOSED


    def __str__(self):
        state_str = "OPEN" if self.state == self.GRID_STAT_OPEN else "CLOSED"
        msg = "L: {:.2f} H: {:.2f} BUY Price: {:<8.2f} State: {:8s}".format(self.lower, self.upper, self.buy_price, state_str)
        return msg



class GridBot:
    def __init__(self, initial_usd, parameters):
        self.parameters = parameters

        # for convenience
        self.lower_limit = parameters['lower_limit']
        self.upper_limit = parameters['upper_limit']
        self.grid_cnt = parameters['grid_cnt']
        self.start_price = parameters['start_price']
        self.grid_width = (self.upper_limit - self.lower_limit)/self.grid_cnt


        # 
        self.initial_usd = initial_usd
        self.usd = self.initial_usd
        self.dcoin = 0
        self.fiat = self.usd
        self.fiat_history = []
        self.grid_profit = 0
        self.grid_profit_history = []
        self.grid_tx_cnt = 0

        self.quantity_per_grid = None
        self.current_price = self.start_price
        self.current_grid_id = None

        self.started = False

        # start, end time
        self.time = None
        self.start_time = None
        self.end_time = None
        self.month_histogram = [0]*12



    def show_grids(self):
        if not self.started:
            return 

        logging.log_msg(misc.datetime_to_str(self.time))
        for grid_id in reversed(range(self.grid_cnt)):
            grid = self.grids[grid_id]
            log_msg = str(grid)
            if grid_id == self.current_grid_id:
                log_msg += "<="
            logging.log_msg(log_msg)
        logging.log_msg("\n")

        days = (self.time - self.start_time).days
        logging.log_msg("start time:      {}".format(misc.datetime_to_str(self.start_time)))
        logging.log_msg("end time:        {}".format(misc.datetime_to_str(self.time)))
        logging.log_msg("lower_limit:     {:.2f}".format(self.lower_limit))
        logging.log_msg("upper_limit:     {:.2f}".format(self.upper_limit))
        logging.log_msg("grid cnt:        {:.2f}".format(self.grid_cnt))
        logging.log_msg("start price:     {:.2f}".format(self.start_price))
        logging.log_msg("avg cost :       {:.2f}".format(self.get_avg_cost()))
        logging.log_msg("price:           {:.2f}".format(self.current_price))
        logging.log_msg("grid width:      {:.2f}".format(self.grid_width))
        logging.log_msg("Quantity/Grid:   {:.4f}".format(self.quantity_per_grid))
        logging.log_msg("Profit/Grid:     {:.4f}".format(self.quantity_per_grid * self.grid_width))
        logging.log_msg("USD:             {:.2f}".format(self.usd))
        logging.log_msg("dcoin:           {:.2f}".format(self.dcoin))
        logging.log_msg("fiat:            {:.2f}".format(self.get_fiat()))
        logging.log_msg("grid tx cnt:     {}".format(self.grid_tx_cnt))
        tx_cnt_per_day = 0 if days == 0 else self.grid_tx_cnt/days
        logging.log_msg("grid tx cnt/Day: {:.2f}".format(tx_cnt_per_day))
        logging.log_msg("APY:             {:.2f}%".format(365*tx_cnt_per_day * self.quantity_per_grid * self.grid_width/10000*100))
        logging.log_msg("grid profit:     {:.2f}".format(self.grid_profit))

        logging.log_msg("trading histogram")
        for i in range(12):
            logging.log_msg("{:2d}: {}".format(i+1, self.month_histogram[i]))




    def get_fiat(self):
        return self.usd + self.dcoin * self.current_price


    def update_history(self):
        self.fiat_history.append(self.get_fiat())
        self.grid_profit_history.append(self.grid_profit)

    def get_avg_cost(self):
        return self.initial_usd / (self.quantity_per_grid * self.grid_cnt)




    def get_grid_id(self, price):
        grid_id = int((price - self.lower_limit) / self.grid_width)
        if grid_id >= self.grid_cnt:
            return self.grid_cnt
        elif grid_id < 0:
            return -1
        else:
            return grid_id


    def open_grid(self, grid_id, buy_price):
        grid = self.grids[grid_id]
        assert (grid.state == grid.GRID_STAT_CLOSED)
        grid.buy_price = buy_price
        grid.state = grid.GRID_STAT_OPEN
        self.usd -= buy_price * self.quantity_per_grid
        self.dcoin += self.quantity_per_grid
        logging.log_msg("{}: open grid, grid_id: {}, buy_price: {:.2f}, qty: {:.2f}".format(misc.datetime_to_str(self.time), grid_id, buy_price, self.quantity_per_grid))


    def close_grid(self, grid_id, sell_price):
        grid = self.grids[grid_id]
        assert (grid.state == grid.GRID_STAT_OPEN)

        grid.state = grid.GRID_STAT_CLOSED
        self.usd += sell_price * self.quantity_per_grid
        self.dcoin -= self.quantity_per_grid
        self.grid_profit += self.quantity_per_grid * (sell_price - grid.buy_price)


        self.grid_tx_cnt += 1
        self.month_histogram[self.time.date().month-1] += 1


        logging.log_msg("{}: close grid, grid_id: {}, sell_price: {:.2f}, buy_price: {:.2f}, qty: {:.2f}".format(misc.datetime_to_str(self.time), grid_id, sell_price, grid.buy_price, self.quantity_per_grid))


    def start(self):
        self.grids = []

        # creat grid objects
        for i in range(self.grid_cnt):
            grid = Grid()
            grid.lower = self.lower_limit + i * self.grid_width
            grid.upper = grid.lower + self.grid_width
            self.grids.append(grid)

        # figure out quantity per grid
        current_grid_id = self.get_grid_id(self.start_price)
        assert (current_grid_id != None)
        self.current_grid_id = current_grid_id
        self.quantity_per_grid = self.initial_usd / ((self.grid_cnt - current_grid_id)*self.start_price + self.lower_limit * current_grid_id + current_grid_id * (current_grid_id - 1)/2*self.grid_width)


        # open grids 
        for i in range(current_grid_id, self.grid_cnt):
            self.open_grid(i, self.start_price)

        self.started = True

        logging.log_msg("{}: start rob".format(misc.datetime_to_str(self.time)))
        self.start_time = self.time


    def update_price(self, time, price):
        self.time = time
        self.current_price = price

        # start rob?
        if self.started == False:
            if abs(price-self.start_price)/self.start_price <= 0.001:
                self.start()
                self.show_grids()
            self.update_history()
            return 

        new_grid_id = self.get_grid_id(price)

        if new_grid_id > self.current_grid_id:
            for grid_id in range(max(0, self.current_grid_id), min(new_grid_id, self.grid_cnt)):
                grid = self.grids[grid_id]
                if grid.state == grid.GRID_STAT_OPEN and price >= grid.upper:
                    self.close_grid(grid_id, grid.upper)
        elif new_grid_id < self.current_grid_id:
            for grid_id in range(min(self.current_grid_id, self.grid_cnt-1), max(0, new_grid_id), -1):
                grid = self.grids[grid_id]
                if grid.state == grid.GRID_STAT_CLOSED and price <= grid.lower:
                    self.open_grid(grid_id, grid.lower)

        self.current_grid_id = new_grid_id

        self.update_history()


    def monitor(self):
        for i in range(len(self.klines)):
            self.clock_tick(i)

    def plt_asset(self):
        plt.rcParams["figure.figsize"] = (24,18)
        fig, ax = plt.subplots()
        ax.plot(range(len(self.fiat_history)), self.fiat_history, label='fiat', marker='o')
        ax.plot(range(len(self.grid_profit_history)), self.grid_profit_history, label='grid profit', marker='o')
        plt.legend()
        plt.show()

if __name__ == "__main__":

    kline_file_name = "./klines/btcbusd_klines_2022-01-01_07_00_00_to_2022-11-30_01_05_00.pkl"
    #  kline_file_name = "./klines/btcusdt_klines_2022-01-01_07_00_00_to_2022-03-26_08_00_00.pkl"
    #  kline_file_name = "./klines/ethusdt_klines_2022-01-01_07_00_00_to_2022-04-22_18_29_00.pkl"
    #  kline_file_name = "./klines/ethusdt_klines_2021-01-01_07_00_00_to_2021-12-31_07_00_00.pkl"
    #  kline_file_name = "./klines/ethusdt_klines_2020-01-01_07_00_00_to_2020-12-31_07_00_00.pkl"
    #  kline_file_name = "./klines/ethbusd_klines_2022-01-01_07_00_00_to_2022-05-03_22_14_00.pkl"

    with open(kline_file_name, "rb") as tf:
        klines = pickle.load(tf)

    grid_bot = GridBot(10000, grid_bot_parameters)

    start_date = datetime.datetime(2022, 11, 25).date()

    for _ in klines:
        current_stick = kline.CandleStick(_)
        if current_stick.get_open_time().date() > start_date:
            grid_bot.update_price(current_stick.get_open_time(), current_stick.get_close_price())

    #  grid_bot.update_price("H:M:S", 2000)
    #  grid_bot.update_price("H:M:S", 800)
    #  grid_bot.update_price("H:M:S", 4100)
    #  grid_bot.update_price("H:M:S", 3950)
    #  grid_bot.update_price("H:M:S", 4000)
    #  grid_bot.update_price("H:M:S", 3999)
    #  grid_bot.update_price("H:M:S", 3900)
    #  grid_bot.update_price("H:M:S", 60000)
    #  grid_bot.update_price("H:M:S", 3000)
    #  grid_bot.update_price("H:M:S", 4000)
    #  grid_bot.show_grids()

    grid_bot.show_grids()
    grid_bot.plt_asset()

