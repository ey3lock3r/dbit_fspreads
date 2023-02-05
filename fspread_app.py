# Loading an Environment Variable File with dotenv
from dotenv import load_dotenv
load_dotenv()
import os

from Bot import CBot, FILE
from exchange import Deribit_Exchange

import yaml
import logging.config
from datetime import date

def main():

    # Подгружаем конфиг
    with open('./config.yaml','r') as f:
        config = yaml.load(f.read(), Loader = yaml.FullLoader)

    if config['exchange']['env'] == 'prod':
        config['exchange']['auth']['prod']['client_id'] = os.getenv('client_id')
        config['exchange']['auth']['prod']['client_secret'] = os.getenv('client_secret')
    
    logging.addLevelName(FILE,"FILE")
    logging.config.dictConfig(config['logging'])
    
    deribit_exch = Deribit_Exchange(**config['exchange'], env=config['env'])
    bot = CBot(**config['bot'], exchange=deribit_exch, env=config['env'])
    bot.run()


if __name__ == '__main__':
    main()