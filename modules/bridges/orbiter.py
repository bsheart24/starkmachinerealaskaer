import json
import random

from modules import Bridge, Logger
from modules.interfaces import BridgeExceptionWithoutRetry, SoftwareExceptionWithoutRetry
from utils.tools import helper
from config import ORBITER_CONTRACTS, ORBITER_ABI, TOKENS_PER_CHAIN
from general_settings import GLOBAL_NETWORK
from web3 import AsyncWeb3


class Orbiter(Bridge, Logger):
    def __init__(self, client):
        self.client = client
        Logger.__init__(self)
        Bridge.__init__(self, client)

    @staticmethod
    def get_maker_data(from_id:int, to_id:int, token_name: str):

        path = random.choice(['orbiter_maker1.json', 'orbiter_maker2.json'])
        with open(f'./data/services/{path}') as file:
            data = json.load(file)

        maker_data = data[f"{from_id}-{to_id}"][f"{token_name}-{token_name}"]

        bridge_data = {
            'maker': maker_data['makerAddress'],
            'fee': maker_data['tradingFee'],
            'min_amount': maker_data['minPrice'],
            'max_amount': maker_data['maxPrice'],
        } | ({'sender': maker_data['sender']} if GLOBAL_NETWORK == 9 else {})

        if bridge_data:
            return bridge_data
        raise BridgeExceptionWithoutRetry(f'That bridge is not active!')

    @helper
    async def bridge(
            self, chain_from_id:int, private_keys:dict = None, bridge_data:tuple = None, need_fee:bool = False
    ):
        if GLOBAL_NETWORK == 9 and chain_from_id == 9:
            await self.client.initialize_account()
        elif GLOBAL_NETWORK == 9 and chain_from_id != 9:
            await self.client.session.close()
            self.client = await self.client.initialize_evm_client(private_keys['evm_key'], chain_from_id)

        from_chain, to_chain, amount, to_chain_id, token_name = bridge_data

        bridge_info = f'{amount} {token_name} from {from_chain["name"]} to {to_chain["name"]}'

        if not need_fee:
            self.logger_msg(*self.client.acc_info, msg=f'Bridge on Orbiter: {bridge_info}')

        bridge_data = self.get_maker_data(from_chain['id'], to_chain['id'], token_name)
        destination_code = 9000 + to_chain['id']
        decimals = await self.client.get_decimals(token_name)
        fee = int(float(bridge_data['fee']) * 10 ** decimals)
        amount_in_wei = int(amount * 10 ** decimals)
        full_amount = int(round(amount_in_wei + fee, -4) + destination_code)

        if need_fee:
            return round(float(full_amount / 10 ** decimals), 6)

        min_price, max_price = bridge_data['min_amount'], bridge_data['max_amount']

        if from_chain['name'] != 'Starknet' and to_chain['name'] == 'Starknet':

            contract = self.client.get_contract(ORBITER_CONTRACTS["evm_contracts"][self.client.network.name],
                                                ORBITER_ABI['evm_contract'])

            receiver = await self.get_address_for_bridge(private_keys['stark_key'], stark_key_type=True)

            transaction = [await contract.functions.transfer(
                AsyncWeb3.to_checksum_address(bridge_data['maker']),
                "0x03" + f'{receiver[2:]:0>64}'
            ).build_transaction(await self.client.prepare_transaction(value=full_amount))]

        elif from_chain['name'] == 'Starknet' and to_chain['name'] != 'Starknet':

            contract = await self.client.get_contract(ORBITER_CONTRACTS["stark_contract"])
            eth_address = TOKENS_PER_CHAIN['Starknet']['ETH']

            approve_call = self.client.get_approve_call(eth_address, ORBITER_CONTRACTS['stark_contract'],
                                                        unlim_approve=True)

            bridge_call = contract.functions["transferERC20"].prepare(
                eth_address,
                int(bridge_data['maker'], 16),
                full_amount,
                int(await self.get_address_for_bridge(private_keys['evm_key'], stark_key_type=False), 16)
            )

            transaction = approve_call, bridge_call
        else:
            raise SoftwareExceptionWithoutRetry('Only bridge into/from Starknet supported')

        if min_price <= amount <= max_price:
            balance_in_wei, _, _ = await self.client.get_token_balance(token_name)

            if balance_in_wei > full_amount:

                if int(f"{full_amount}"[-4:]) != destination_code:
                    raise SoftwareExceptionWithoutRetry('Math problem in Python. Machine will save your money =)')

                old_balance_on_dst = await self.client.wait_for_receiving(
                    token_name=token_name, chain_id=to_chain_id, check_balance_on_dst=True
                )

                result = await self.client.send_transaction(*transaction)

                self.logger_msg(*self.client.acc_info,
                                msg=f"Bridge complete. Note: wait a little for receiving funds", type_msg='success')

                await self.client.wait_for_receiving(to_chain_id, old_balance_on_dst, token_name=token_name)

                return result

            else:
                raise BridgeExceptionWithoutRetry(f'Insufficient balance!')
        else:
            raise BridgeExceptionWithoutRetry(f"Limit range for bridge: {min_price} – {max_price} {token_name}!")
