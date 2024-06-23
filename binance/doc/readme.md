# Quick Start
1. Register an account with Binance.
   https://www.binance.com/en/register?ref=21880128
2. Generate an API Key and assign relevant permissions.
   https://www.binance.com/en/my/settings/api-management


# install python modules
pip3 install python-binance
pip3 install pandas
pip3 install matplotlib

# Live EMA trading
## step 1
replace the API-key with yours in "../config/trade_config.json"

## step 2
python3 live_trader.py

## step3
the trading history and assets are tracked in  ../data/

# python-binance API reference
https://github.com/sammchardy/python-binance


# Auto Trade Engine controller
1. Submit a cakebusd or cakeusdt order
2. Using the order price to convey information to the "auto trading engine"
   X.YYZ
   X: even -- fluctuation window mode
      old  -- moving average mode

   YY: the moving average window size, only meaningful when the moving average mode is enabled
   Z: the delta, 1 means 0.0001, only meaningful when the moving average mode is enabled

   Examples:
   51.994 means enable the moving average mode, set the MA_WINDOW to 99 and delta to 0.0004
   50.000 means enable the fluctuation window mode

3. Once the "auto trading engine" is aware of the cake order, it will take actions below
   a) suspend the auto trading engine
   b) cancel all the open BUSDUSDT orders
   c) decode the cake order price, then update the working mode

4. Cancel the cake order to restart the "auto trading engine". After that the engine will work on the new mode

