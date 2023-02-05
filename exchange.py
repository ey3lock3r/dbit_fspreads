# https://github.com/n-eliseev/deribitsimplebot/blob/master/deribitsimplebot/bot.py
import asyncio
import json
import time
import logging
import numpy as np
import pandas as pd

from datetime import date, datetime, timedelta, timezone
from typing import Union, Optional, NoReturn
import websockets

from exceptions import CBotResponseError , CBotError

class Deribit_Exchange:
    """The class describes the object of a simple bot that works with the Deribit exchange.
    Launch via the run method or asynchronously via start.
    The business logic of the bot itself is described in the worker method."""

    def __init__(self, url: dict = {}, env: str = 'test',
        logger: Union[logging.Logger, str, None] = None):

        self.url = url[env]
        self.env = env
        self.logger = (logging.getLogger(logger) if isinstance(logger,str) else logger)

        if self.logger is None:
            self.logger = logging.getLogger(__name__)

        self.logger.info(f'Exchange initialized!')
        
    def create_message(self, method: str, params: dict = {},
                        mess_id: Union[int, str, None] = None,
                        as_dict: bool = False) -> Union[str, dict] :
        """The method returns an object or a JSON dump string with a body for a request to the exchange API"""

        obj = {
            "jsonrpc" : "2.0",
            "id" : ( str(time.time()).replace('.','_') if mess_id is None else mess_id),
            "method" : method,
            "params" : params
        }

        self.logger.debug(f'Create message = {obj}')

        return obj if as_dict else json.dumps(obj)


    def get_response_result(self, raw_response: str, raise_error: bool = True,
                            result_prop: str = 'result') -> Optional[dict]:
        """Receives the response body from the server, then returns an object
        located in result_prop, or throws an exception if from the server
        received error information
        """

        obj = json.loads(raw_response)

        self.logger.debug(f'Get response = {obj}')

        if result_prop in obj:
            return obj[result_prop]

        if 'error' in obj and raise_error:
            self.keep_alive = False
            self.logger.debug('Error found!')
            self.logger.debug(f'Error: code: {obj["error"]["code"]}')
            self.logger.debug(f'Error: msg: {obj["error"]["message"]}')
            raise CBotResponseError(obj['error']['message'],obj['error']['code'])

        else:
            # self.keep_alive = False
            self.logger.debug('Other unexpected messages!')
            self.logger.debug(f'Object contents: {obj}')

        return None


    async def auth(self, ws, creds=None) -> Optional[dict]:

        if creds is None:
            raise CBotError(f'Credentials Empty!')

        await ws.send(
            self.create_message(
                'public/auth',
                creds
                # self.__credentials
            )
        )

        return self.get_response_result(await ws.recv())

    async def get_instrument(self, ws, instrument_name) -> Optional[dict]:
        self.logger.info('get_instrument')

        prop = {
            'instrument_name': instrument_name
        }

        await ws.send(
            self.create_message(
                'public/get_instrument',
                {**prop}
            )
        )

        return self.get_response_result(await ws.recv())

    async def get_instruments(self, ws) -> Optional[dict]:
        self.logger.info('get_instruments')

        prop = {
            'currency': self.currency,
            'kind': 'option',
            'expired': False
        }

        await ws.send(
            self.create_message(
                'public/get_instruments',
                {**prop}
            )
        )

        return self.get_response_result(await ws.recv())

    async def get_index_price(self, ws, delay = 0) -> Optional[dict]:
        
        self.logger.info('get_index_price')

        await asyncio.sleep(delay)

        prop = { 'index_name': f'{self.currency.lower()}_usd' }

        await ws.send(
            self.create_message(
                'public/get_index_price',
                { 'index_name': f'{self.currency.lower()}_usd' }
            )
        )

        price = self.get_response_result(await ws.recv())
        if 'index_price' in price:
            # self.init_price = price['index_price']
            return price['index_price']

        else:
            raise CBotError(f'Error in get_index_price!')

    async def create_combo(self, ws, params: dict = {},
                            raise_error: bool = True):

        await ws.send(
            self.create_message(
                f'private/create_combo',
                { **params }
            )
        )

        return self.get_response_result(await ws.recv(), raise_error = raise_error)

    async def create_order(self, ws, direction: str = 'sell', params: dict = {},
                            raise_error: bool = True):

        await ws.send(
            self.create_message(
                f'private/{direction}',
                { **params }
            )
        )

        return self.get_response_result(await ws.recv(), raise_error = raise_error)

    async def edit_order(self, ws, params: dict = {}, raise_error: bool = True):

        await ws.send(
            self.create_message(
                f'private/edit',
                { **params }
            )
        )

        return self.get_response_result(await ws.recv(), raise_error = raise_error)

    async def cancel_all(self, ws, raise_error: bool = True):

        await ws.send(
            self.create_message(
                f'private/cancel_all',
                {}
            )
        )

        return self.get_response_result(await ws.recv(), raise_error = raise_error)

    # todo delete, not needed ?
    async def cancel_all_by_currency(self, ws, currency: str = 'BTC', kind: str = 'option',
                            raise_error: bool = True):

        await ws.send(
            self.create_message(
                f'private/cancel_all_by_currency',
                { 'currency': currency,
                  'kind': kind }
            )
        )

        return self.get_response_result(await ws.recv(), raise_error = raise_error)

    async def get_order_state(self, ws, order_id: Union[int, str],
                                raise_error: bool = True):

        await ws.send(
            self.create_message(
                f'private/get_order_state',
                { 'order_id': order_id }
            )
        )

        return self.get_response_result(await ws.recv(), raise_error = raise_error)

    async def get_open_orders_by_currency(self, ws, currency: str = 'BTC', kind: str = 'option',
                                raise_error: bool = True):

        await ws.send(
            self.create_message(
                f'private/get_open_orders_by_currency',
                { 'currency': currency,
                  'kind': kind }
            )
        )

        return self.get_response_result(await ws.recv(), raise_error = raise_error)
    
    async def get_open_orders_by_instrument(self, ws, instrument_name: str = '', oo_type: str = '',
                                raise_error: bool = True):

        await ws.send(
            self.create_message(
                f'private/get_open_orders_by_instrument',
                { 'instrument_name': instrument_name,
                  'type': oo_type }
            )
        )

        return self.get_response_result(await ws.recv(), raise_error = raise_error)

    async def get_user_trades_by_currency(self, ws, currency: str = 'BTC', kind: str = 'option',
                                    raise_error: bool = True):

        await ws.send(
            self.create_message(
                f'private/get_user_trades_by_currency',
                { 'currency': currency,
                  'kind': kind }
            )
        )

        return self.get_response_result(await ws.recv(), raise_error = raise_error)

    async def get_positions(self, ws, currency: str = 'BTC', kind: str = 'option',
                                    raise_error: bool = True):

        await ws.send(
            self.create_message(
                f'private/get_positions',
                { 'currency': currency,
                  'kind': kind }
            )
        )

        return self.get_response_result(await ws.recv(), raise_error = raise_error)

    async def get_order_history_by_currency(self, ws, currency: str = 'BTC', kind: str = 'option',
                                    raise_error: bool = True):

        await ws.send(
            self.create_message(
                f'private/get_order_history_by_currency',
                { 'currency': currency,
                  'kind': kind }
            )
        )

        return self.get_response_result(await ws.recv(), raise_error = raise_error)

    async def get_account_summary(self, ws, currency: str = 'BTC',
                                    raise_error: bool = True):

        await ws.send(
            self.create_message(
                f'private/get_account_summary',
                { 'currency': currency }
            )
        )

        return self.get_response_result(await ws.recv(), raise_error = raise_error)

    async def close_position(self, ws, params, raise_error: bool = True):

        await ws.send(
            self.create_message(
                f'private/close_position',
                { **params }
            )
        )

        self.get_response_result(await ws.recv(), raise_error = raise_error)
        

    async def unsubscribe_all(self, ws) -> Optional[dict]:
        self.logger.info('unsubscribe_all')

        await ws.send(
            self.create_message(
                'public/unsubscribe_all',
                {}
            )
        )

        return self.get_response_result(await ws.recv())