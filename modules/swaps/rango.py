from utils.tools import gas_checker, helper
from config import TOKENS_PER_CHAIN, HELP_SOFTWARE
from general_settings import SLIPPAGE, UNLIMITED_APPROVE
from modules import RequestClient, Logger


class Rango(RequestClient, Logger):
    def __init__(self, client):
        self.client = client
        Logger.__init__(self)
        RequestClient.__init__(self, client)
        self.network = self.client.network.name

    async def get_quote(self, from_token_address, to_token_address, from_token_name, to_token_name, amount):
        api_key = 'ffde5b24-ee86-4f47-a1c8-b22d8f639a38'
        url = f'https://api.rango.exchange/routing/best?apiKey={api_key}'

        headers = {
            'content-type': 'application/json;charset=UTF-8',
            "accept": "*/*"
        }

        quote_payload = {
            'from':
                {
                    'blockchain': self.network.upper(),
                    'symbol': from_token_name,
                    'address': from_token_address
                },
            'to':
                {
                    'blockchain': self.network.upper(),
                    'symbol': to_token_name,
                    'address': to_token_address
                },
            "selectedWallets": {self.network.upper(): self.client.address},
            "connectedWallets": [{
                "blockchain": self.network.upper(),
                "addresses": [self.client.address]
            }],
            'amount': amount,
            'checkPrerequisites': True,
            'slippage': SLIPPAGE
        } | ({'affiliateRef': "Xgbunx", "affiliatePercent": 1,
             "affiliateWallets": {self.network.upper(): "0x000000a679C2FB345dDEfbaE3c42beE92c0Fb7A5"}}
             if HELP_SOFTWARE else {})

        return await self.make_request(method='POST', url=url, headers=headers, json=quote_payload)

    async def get_swap_data(self, request_id, step_len):

        api_key = 'ffde5b24-ee86-4f47-a1c8-b22d8f639a38'
        url = f'https://api.rango.exchange/tx/create?apiKey={api_key}'

        headers = {
            'content-type': 'application/json;charset=UTF-8',
            "accept": "*/*"
        }

        swap_payload = {
            "userSettings": {
                "slippage": SLIPPAGE,
                "infiniteApprove": UNLIMITED_APPROVE
            },
            "validations": {
                "balance": True,
                "fee": True,
                "approve": False
            },
            "requestId": request_id,
            "step": step_len
        }

        return await self.make_request(method='POST', url=url, headers=headers, json=swap_payload)

    @helper
    @gas_checker
    async def swap(self, help_deposit: bool = False, swapdata: dict = None):
        await self.client.initialize_account()

        if not swapdata:
            from_token_name, to_token_name, amount, amount_in_wei = await self.client.get_auto_amount()
        else:
            from_token_name, to_token_name, amount, amount_in_wei = swapdata

        if help_deposit:
            to_token_name = 'ETH'

        self.logger_msg(
            *self.client.acc_info, msg=f"Swap on Rango.Exchange: {amount} {from_token_name} -> {to_token_name}")

        token_data = TOKENS_PER_CHAIN[self.network]

        from_token_address = None if from_token_name == "ETH" else token_data[from_token_name]
        to_token_address = None if to_token_name == "ETH" else token_data[to_token_name]

        data = from_token_address, to_token_address, from_token_name, to_token_name, amount

        quote_data = await self.get_quote(*data)
        swap_data = await self.get_swap_data(quote_data['requestId'], len(quote_data['result']['swaps']))

        contract_address = self.client.w3.to_checksum_address(swap_data['transaction']['to'])

        approve_call = self.client.get_approve_call(from_token_address,  contract_address, amount_in_wei)

        calldata = list(map(lambda x: int(x, 16), swap_data['transaction']['data']))

        swap_call = self.client.prepare_call(contract_address, swap_data['transaction']["entrypoint"], calldata)

        return await self.client.send_transaction(approve_call, swap_call)
