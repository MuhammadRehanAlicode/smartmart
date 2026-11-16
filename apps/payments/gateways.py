"""Payment gateway abstraction.

Add an online gateway by subclassing PaymentGateway, implementing initiate() and verify(), and registering it in
GATEWAYS. A payment may only be marked paid from a VerificationResult that the gateway itself produced from the
provider's signed callback or server-to-server API (see services.record_verified_payment).
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class VerificationResult:
    verified: bool
    reference: str = ""
    amount: Optional[Decimal] = None


class PaymentGateway:
    code = ""
    online = True

    def initiate(self, payment) -> dict:
        raise NotImplementedError

    def verify(self, payload: dict) -> VerificationResult:
        raise NotImplementedError


class CashOnDeliveryGateway(PaymentGateway):
    code = "cod"
    online = False

    def initiate(self, payment) -> dict:
        return {}

    def verify(self, payload):
        raise NotImplementedError("Cash on delivery is collected by the courier; there is no provider to verify.")


GATEWAYS = {"cod": CashOnDeliveryGateway()}


def get_gateway(code):
    try:
        return GATEWAYS[code]
    except KeyError:
        raise ValueError(f"Unknown payment method: {code}")
