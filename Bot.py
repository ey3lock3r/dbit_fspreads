# https://github.com/n-eliseev/deribitsimplebot/blob/master/deribitsimplebot/bot.py

import time
import asyncio
import concurrent.futures
import logging
import pandas as pd
import traceback

from datetime import date, datetime, timedelta, timezone
from typing import Union, Optional, NoReturn
from exceptions import CBotError

import websockets

FILE = 60

class CBot:
    """The class describes the object of a simple bot that works with the Deribit exchange.
    Launch via the run method or asynchronously via start.
    The business logic of the bot itself is described in the worker method."""

    def __init__(self, auth: dict, exchange, interval: int = 2, im: dict = {}, mtype: str = 'sm',
        currency: str = 'BTC', env: str = 'test', trading: bool = False, order_size: float = 0.1, risk_perc: float = 0.5,
        logger: Union[logging.Logger, str, None] = None):

        self.__credentials = auth[env]
        self.env = env
        self.trading = trading

        self.interval = interval
        self.exchange = exchange

        self.currency = currency
        self.risk_perc = risk_perc 
        self.margin = im[mtype]

        self.logger = (logging.getLogger(logger) if isinstance(logger,str) else logger)
        if self.logger is None:
            self.logger = logging.getLogger(__name__)

        self.init_vals()
        
        self.logger.info('Bot initialized!')

    @property
    def keep_alive(self) -> bool :
        return self._keep_alive

    @keep_alive.setter
    def keep_alive(self, ka: bool):
        self._keep_alive = ka

    def init_vals(self):
        self.stop = False
        self.keep_alive = True
        self.orders = {}
        self.fs_data = {}
        self.price = 0.0

    async def fetch_fspread_data(self):
        self.logger.info(f'start fetch_fspread_data listener...')

        fsdate = self.get_next_friday()
        params = {
            'trades': [{
                'instrument_name': f'BTC-{fsdate}',
                'amount'         : 1,
                'direction'      : 'sell'
            },
            {
                'instrument_name': 'BTC-PERPETUAL',
                'amount'         : 1,
                'direction'      : 'buy'
            }]
        }

        instrument = ''
        async for websocket in websockets.connect(self.exchange.url):

            await self.exchange.auth(websocket, self.__credentials)

            if not instrument:
                res = await self.exchange.create_combo(websocket, params)
                if 'id' in res:
                    instrument = res['id']
                    self.instrument = instrument
                else:
                    self.logger.info('Instrument id not in response: Error in create_combo...')
                    return

            await websocket.send(
                self.exchange.create_message(
                    'private/subscribe',
                    { "channels": [f'ticker.{instrument}.raw'] }
                )
            )
            await websocket.send(
                self.exchange.create_message(
                    'private/subscribe',
                    { "channels": [f'ticker.BTC-PERPETUAL.raw'] }
                )
            )
            index_name = f'{self.currency.lower()}_usd'
            self.index_name = index_name
            await websocket.send(
                self.exchange.create_message(
                    'private/subscribe',
                    { "channels": [f'deribit_price_index.{index_name}'] }
                )
            )
            self.fs_data[instrument]      = {'bid': 0, 'ask': 0}
            self.fs_data['BTC-PERPETUAL'] = {'bid': 0, 'ask': 0}
            self.fs_data[index_name] = 0

            data = None
            while self.keep_alive:

                try:    
                    message = self.exchange.get_response_result(await websocket.recv(), result_prop='params')

                    if (not message is None and
                            ('channel' in message) and
                            ('data' in message)):

                        data = message['data']

                        if 'instrument_name' in data:
                            self.fs_data[data['instrument_name']].update({
                                'bid': data['best_bid_price'],
                                'ask': data['best_ask_price']
                            })
                        else:
                            self.fs_data[index_name] = data['price']

                    else:
                        self.logger.info('Data not updated > ')
                        self.logger.info(f'Message: {message}')

                
                except Exception as E:
                    self.logger.info(f'Error in fetch_fspread_data: {E}')
                    self.logger.info(f'Reconnecting fetch_fspread_data...')
                    break
            
            if not self.keep_alive:
                break

        self.logger.info('fetch_fspread_data listener ended..')
    
    def get_ord_size(self):
        ord_size = self.equity * self.risk_perc
        ord_size /= self.margin / 2 # 0.03? margin 2? pm acct
        ord_size *= self.fs_data[self.index_name]
        return ord_size - ord_size % 10

    async def trade_fs(self, delay: int = 0):
        self.logger.info('trade_fs')
        await asyncio.sleep(delay)

        fs_data = self.fs_data[self.instrument]
        err_loc = ''

        while self.keep_alive:
            async with websockets.connect(self.exchange.url) as websocket:
                try:
                    await self.exchange.auth(websocket, self.__credentials)
                    
                    err_loc = 'get_account_summary'
                    res = await self.exchange.get_account_summary(websocket, currency=self.currency)
                    self.equity = float(res['equity'])
                    err_loc = 'get_positions'
                    open_pos = await self.exchange.get_positions(websocket, currency=self.currency)
                    err_loc = 'get_open_orders_by_instrument'
                    open_ord = await self.exchange.get_open_orders_by_instrument(websocket, self.instrument, 'limit')
                    ord_size = self.get_ord_size()
                    
                    params = {
                        'instrument_name' : self.instrument,
                        'type'            : 'limit',
                        'price'           : fs_data['ask'] - 0.5,
                        'amount'          : ord_size,
                        'post_only'       : True,
                        'max_show'        : 0
                    }

                    if not open_pos and not open_ord and fs_data['ask'] >= 10:
                        err_loc = 'create_order sell'
                        self.logger.info(f'Selling {ord_size} amount of {self.instrument} at {fs_data["ask"] - 1}')
                        self.ord_size = ord_size
                        await self.exchange.create_order(websocket, 'sell', params)

                    if open_pos and not open_ord:
                        err_loc = 'create_order buy'
                        params.update({
                            'price' : fs_data['bid'] + 0.5,
                            'amount': self.ord_size,
                            'reduce_only': True
                        })
                        self.logger.info(f'Buying {self.ord_size} amount of {self.instrument} at {fs_data["bid"] + 1}')
                        await self.exchange.create_order(websocket, 'buy', params)

                    if open_ord:
                        params = {}
                        open_ord = open_ord[0]

                        if open_ord['direction'] == 'sell' and fs_data['ask'] != open_ord['price']:
                            err_loc = 'edit_order sell'
                            params = {
                                'order_id': open_ord['order_id'],
                                'price'   : fs_data['ask'] - 0.5
                            }
                            await self.exchange.edit_order(websocket, params)

                        if open_ord['direction'] == 'buy' and fs_data['bid'] != open_ord['price']:
                            err_loc = 'edit_order buy'
                            params = {
                                'order_id': open_ord['order_id'],
                                'price'   : fs_data['bid'] + 0.5
                            }
                            await self.exchange.edit_order(websocket, params)
                
                except Exception as E:
                    self.logger.info(f'Error in trade_fs: {err_loc} : {E}') 

            await asyncio.sleep(delay)

    def get_next_friday(self):
        today = datetime.now(timezone.utc) # date.today()
        td_weekday = today.weekday()
        if td_weekday != 4:
            today += timedelta( (4-td_weekday) % 7 )

        else:
            today += timedelta( (3-td_weekday) % 7+1 )
        
        self.nx_friday = today
        today = today.strftime(f"{today.day}%b%y").upper()
        self.logger.info(f'Next friday is {today}')
        return today

    async def start(self):
        """Starts the bot with the parameters for synchronization.
        Synchronization will be carried out only if the store (store) is specified """

        self.logger.info('start running')

        tasks = []

        tasks.append(asyncio.create_task(self.fetch_fspread_data()))
        tasks.append(asyncio.create_task(self.trade_fs(self.interval)))
        tasks.append(asyncio.create_task(self.end_of_day()))

        self.logger.info(f'Tasks started...')

        await asyncio.gather(*tasks)

        self.logger.info('Tasks ended!')

    async def end_of_day(self):

        ts = self.nx_friday.timestamp()

        await asyncio.sleep( ts - int(datetime.now(timezone.utc).timestamp()) % ts - 10)

        self.keep_alive = False

        await self.close_all_positions(self.instrument)

        self.logger.info('End of trading week!')
        await asyncio.sleep( 120 )  # sleep/wait for 2 minutes before starting

    async def close_all_positions(self):

        async with websockets.connect(self.exchange.url) as websocket:
            await self.auth(websocket)

            try:
                # cancel all open orders and open possitions
                await self.exchange.cancel_all(websocket)
                await asyncio.sleep(0.5)

                self.logger.info('Closing position BTC-PERPETUAL')
                params = { 
                        'instrument_name': 'BTC-PERPETUAL',
                        'type' : 'limit',
                        'price': self.fs_data['BTC-PERPETUAL']['ask']
                    }
                await self.exchange.close_position(websocket, params, raise_error = False)
                # await asyncio.sleep(0.5)

            except Exception as E:
                self.logger.info(f'Error in close_all_positions: {E}')
        
        self.logger.info('All positions closed!')
        
    def run(self) -> NoReturn:
        """Wrapper for start to run without additional libraries for managing asynchronous"""

        self.logger.info('Run started')
        loop = asyncio.get_event_loop()

        if self.exchange.env == 'test':
            self.start = self.test_start

        while True:
            try:
                loop.run_until_complete(self.start())
            
            except KeyboardInterrupt:
                self.keep_alive = False
                self.stop = True
                self.logger.info('Keyboard Interrupt detected...')

            except Exception as E:
                self.keep_alive = False
                self.logger.info(f'Error in run: {E}')
                self.logger.info(traceback.print_exc())

            finally:
                time.sleep(1)
                loop.run_until_complete(self.grace_exit())
                self.logger.info('Gracefully exit')
                
                for task in asyncio.all_tasks(loop):
                    task.cancel()

                time.sleep(1)

                if self.stop or self.exchange.env == 'test':
                    break
                    
                self.init_vals()

    async def grace_exit(self):
        self.logger.info('grace_exit')
        async with websockets.connect(self.exchange.url) as websocket:
            await self.exchange.unsubscribe_all(websocket)