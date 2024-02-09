import io
import os
import sys
import json
import random
import asyncio
import functools
import traceback
import msoffcrypto
import pandas as pd

from getpass import getpass
from termcolor import cprint
from datetime import datetime, timedelta
from web3.exceptions import TimeExhausted, ContractLogicError
from aiohttp import ClientSession, TCPConnector
from msoffcrypto.exceptions import DecryptionError, InvalidKeyError

from general_settings import (
    SLEEP_TIME,
    GLOBAL_NETWORK,
    SLEEP_TIME_RETRY,
    MAXIMUM_RETRY,
    MAXIMUM_GWEI,
    GAS_CONTROL,
    SLEEP_TIME_GAS,
    EXCEL_PASSWORD,
    CONTROL_TIMES_FOR_SLEEP,
    ACCOUNTS_IN_STREAM,
    SOFTWARE_MODE,
    EXCEL_PAGE_NAME, SLEEP_TIME_STREAM
)


async def sleep(self, min_time=SLEEP_TIME[0], max_time=SLEEP_TIME[1]):
    duration = random.randint(min_time, max_time)
    print()
    self.logger_msg(*self.client.acc_info, msg=f"💤 Sleeping for {duration} seconds")
    await asyncio.sleep(duration)


def get_accounts_data():
    try:
        decrypted_data = io.BytesIO()
        with open('./data/accounts_data.xlsx', 'rb') as file:
            if EXCEL_PASSWORD:
                cprint('⚔️ Enter the password degen', color='light_blue')
                password = getpass()
                office_file = msoffcrypto.OfficeFile(file)

                try:
                    office_file.load_key(password=password)
                except msoffcrypto.exceptions.DecryptionError:
                    cprint('\n⚠️ Incorrect password to decrypt Excel file! ⚠️', color='light_red', attrs=["blink"])
                    raise DecryptionError('Incorrect password')

                try:
                    office_file.decrypt(decrypted_data)
                except msoffcrypto.exceptions.InvalidKeyError:
                    cprint('\n⚠️ Incorrect password to decrypt Excel file! ⚠️', color='light_red', attrs=["blink"])
                    raise InvalidKeyError('Incorrect password')

                except msoffcrypto.exceptions.DecryptionError:
                    cprint('\n⚠️ Set password on your Excel file first! ⚠️', color='light_red', attrs=["blink"])
                    raise DecryptionError('Excel without password')

                office_file.decrypt(decrypted_data)

                try:
                    wb = pd.read_excel(decrypted_data, sheet_name=EXCEL_PAGE_NAME)
                except ValueError as error:
                    cprint('\n⚠️ Wrong page name! ⚠️', color='light_red', attrs=["blink"])
                    raise ValueError(f"{error}")
            else:
                try:
                    wb = pd.read_excel(file, sheet_name=EXCEL_PAGE_NAME)
                except ValueError as error:
                    cprint('\n⚠️ Wrong page name! ⚠️', color='light_red', attrs=["blink"])
                    raise ValueError(f"{error}")

            accounts_data = {}
            for index, row in wb.iterrows():
                account_name = row["Name"]
                private_key = row["Private Key"]
                private_key_evm = row["Private Key EVM"] if GLOBAL_NETWORK == 9 else 0x123
                proxy = row["Proxy"]
                cex_address = row['CEX address']
                accounts_data[int(index) + 1] = {
                    "account_number": account_name,
                    "private_key_evm": private_key_evm,
                    "private_key": private_key,
                    "proxy": proxy,
                    "cex_wallet": cex_address,
                }

            acc_name, priv_key_evm, priv_key, proxy, cex_wallet = [], [], [], [], []
            for k, v in accounts_data.items():
                acc_name.append(v['account_number'] if isinstance(v['account_number'], (int, str)) else None)
                priv_key_evm.append(v['private_key_evm'])
                priv_key.append(v['private_key'])
                proxy.append(v['proxy'] if isinstance(v['proxy'], str) else None)
                cex_wallet.append(v['cex_wallet'] if isinstance(v['cex_wallet'], str) else None)

            acc_name = [str(item) for item in acc_name if item is not None]
            proxy = [item for item in proxy if item is not None]
            cex_wallet = [item for item in cex_wallet if item is not None]

            return acc_name, priv_key_evm, priv_key, proxy, cex_wallet
    except (DecryptionError, InvalidKeyError, DecryptionError, ValueError):
        sys.exit()

    except ImportError:
        cprint(f'\nAre you sure about EXCEL_PASSWORD in general_settings.py?', color='light_red')
        sys.exit()

    except Exception as error:
        cprint(f'\nError in <get_accounts_data> function! Error: {error}\n', color='light_red')
        sys.exit()


def clean_stark_file():
    with open('./data/services/stark_data.json', 'w') as file:
        file.truncate(0)


def clean_progress_file():
    with open('./data/services/wallets_progress.json', 'w') as file:
        file.truncate(0)


def clean_google_progress_file():
    with open('./data/services/google_progress.json', 'w') as file:
        file.truncate(0)


def clean_gwei_file():
    with open('./data/services/maximum_gwei.json', 'w') as file:
        file.truncate(0)


def check_progress_file():
    file_path = './data/services/wallets_progress.json'

    if os.path.getsize(file_path) > 0:
        return True
    else:
        return False


def check_google_progress_file():
    file_path = './data/services/google_progress.json'

    if os.path.getsize(file_path) > 0:
        return True
    else:
        return False


def drop_date():
    current_date = datetime.now()
    random_months = random.randint(1, 4)

    future_date = current_date + timedelta(days=random_months * 30)

    return future_date.strftime("%Y.%m.%d")


def create_cex_withdrawal_list():
    from config import ACCOUNT_NAMES, CEX_WALLETS
    cex_data = {}

    if ACCOUNT_NAMES and CEX_WALLETS:
        with open('./data/services/cex_withdraw_list.json', 'w') as file:
            for account_name, cex_wallet in zip(ACCOUNT_NAMES, CEX_WALLETS):
                cex_data[str(account_name)] = cex_wallet
            json.dump(cex_data, file, indent=4)
        cprint('✅ Successfully added and saved CEX wallets data', 'light_blue')
        cprint('⚠️ Check all CEX deposit wallets by yourself to avoid problems', 'light_yellow', attrs=["blink"])
    else:
        cprint('❌ Put your wallets into files, before running this function', 'light_red')


def helper(func):
    @functools.wraps(func)
    async def wrapper(self, *args, **kwargs):
        from modules.interfaces import (
            PriceImpactException,BlockchainException, SoftwareException, SoftwareExceptionWithoutRetry,
            BlockchainExceptionWithoutRetry
        )

        attempts = 0
        error = None
        stop_flag = False
        try:
            while attempts <= MAXIMUM_RETRY:
                try:
                    return await func(self, *args, **kwargs)
                except (PriceImpactException, BlockchainException, SoftwareException, SoftwareExceptionWithoutRetry,
                        BlockchainExceptionWithoutRetry, asyncio.exceptions.TimeoutError, TimeExhausted, ValueError,
                        ContractLogicError) as err:
                    error = err
                    attempts += 1

                    msg = f'{error} | Try[{attempts}/{MAXIMUM_RETRY + 1}]'
                    if isinstance(error, asyncio.exceptions.TimeoutError):
                        error = 'Connection to RPC is not stable'
                        await self.client.change_rpc()
                        msg = f'{error} | Try[{attempts}/{MAXIMUM_RETRY + 1}]'

                    elif isinstance(error, SoftwareExceptionWithoutRetry):
                        stop_flag = True
                        msg = f'{error}'

                    elif isinstance(error, (BlockchainException, BlockchainExceptionWithoutRetry)):

                        if any([i in str(error) for i in ['insufficient funds', 'gas required']]):
                            stop_flag = True
                            network_name = self.client.network.name
                            msg = f'Insufficient funds on {network_name}, software will stop this action\n'
                        else:
                            if isinstance(error, BlockchainExceptionWithoutRetry):
                                stop_flag = True
                                msg = f'{error}'

                            self.logger_msg(
                                self.client.account_name,
                                None, msg=f'Maybe problem with node: {self.client.rpc}', type_msg='warning')
                            await self.client.change_rpc()

                    self.logger_msg(self.client.account_name, None, msg=msg, type_msg='error')

                    if stop_flag:
                        break

                    if attempts > MAXIMUM_RETRY:
                        self.logger_msg(self.client.account_name,
                                        None, msg=f"Tries are over, software will stop module\n", type_msg='error')
                    else:
                        await sleep(self, *SLEEP_TIME_RETRY)

                except Exception as error:
                    msg = f'Unknown Error. Description: {error}'
                    self.logger_msg(self.client.account_name, None, msg=msg, type_msg='error')
                    traceback.print_exc()
                    break
        finally:
            await self.client.session.close()
        return False
    return wrapper


def gas_checker(func):
    @functools.wraps(func)
    async def wrapper(self, *args, **kwargs):
        if GAS_CONTROL:
            await asyncio.sleep(1)
            print()
            flag = False
            counter = 0
            self.logger_msg(self.client.account_name, None, f"Checking for gas price")
            while True:
                gas = float(f"{(await self.client.get_gas_price()):.2f}")
                if gas < get_max_gwei_setting():
                    await asyncio.sleep(1)
                    self.logger_msg(self.client.account_name,
                                    None, f"{gas} Gwei | Gas price is good", type_msg='success')
                    await asyncio.sleep(1)
                    if flag and counter == CONTROL_TIMES_FOR_SLEEP and SOFTWARE_MODE:
                        account_number = random.randint(1, ACCOUNTS_IN_STREAM)
                        sleep_duration = tuple(x * account_number for x in SLEEP_TIME_STREAM)
                        await sleep(self, *sleep_duration)
                    return await func(self, *args, **kwargs)
                else:
                    flag = True
                    counter += 1
                    await asyncio.sleep(1)
                    self.logger_msg(
                        self.client.account_name, None,
                        f"{gas} Gwei | Gas is too high. Next check in {SLEEP_TIME_GAS} second", type_msg='warning')
                    await asyncio.sleep(SLEEP_TIME_GAS)
        return await func(self, *args, **kwargs)
    return wrapper


def get_max_gwei_setting():
    file_path = './data/services/maximum_gwei.json'
    data = {}

    try:
        with open(file_path, 'r') as file:
            data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        data['maximum_gwei'] = MAXIMUM_GWEI

    with open(file_path, 'w') as file:
        json.dump(data, file, indent=4)

    return data['maximum_gwei']


async def get_eth_price():
    try:
        url = 'https://api.coingecko.com/api/v3/simple/price'

        params = {
            'ids': 'ethereum',
            'vs_currencies': 'usd'
        }

        async with ClientSession(connector=TCPConnector(verify_ssl=False)) as session:
            async with session.get(url=url, params=params) as response:
                data = await response.json()
                if response.status == 200:
                    return data['ethereum']['usd']
    except Exception as error:
        cprint(f'\nError in <get_eth_price> function! Error: {error}\n', color='light_red')
