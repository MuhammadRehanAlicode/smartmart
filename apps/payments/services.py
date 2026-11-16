from django.utils import timezone

from .gateways import get_gateway
from .models import Payment


class PaymentError(Exception):
    pass


def create_payment(order, method="cod"):
    gateway = get_gateway(method)
    payment = Payment.objects.create(order=order, method=method, amount=order.total)
    gateway.initiate(payment)
    return payment


def mark_cash_collected(order):
    """COD only: called when the courier hands the order over and collects cash."""
    payment = order.payments.filter(method=Payment.Method.COD, status=Payment.Status.PENDING).first()
    if payment is None:
        raise PaymentError("There is no pending cash-on-delivery payment for this order.")
    payment.status, payment.paid_at = Payment.Status.PAID, timezone.now()
    payment.save(update_fields=["status", "paid_at"])
    return payment


def record_verified_payment(payment, result):
    """The ONLY way an online payment becomes paid: a verified provider result for the right amount."""
    gateway = get_gateway(payment.method)
    if not gateway.online:
        raise PaymentError("This payment method is not an online payment.")
    if not getattr(result, "verified", False):
        raise PaymentError("Payment was not verified by the provider.")
    if result.amount is not None and result.amount != payment.amount:
        raise PaymentError("Verified amount does not match the order.")
    if payment.status == Payment.Status.PAID:
        return payment
    payment.status, payment.paid_at, payment.provider_reference = Payment.Status.PAID, timezone.now(), result.reference
    payment.save(update_fields=["status", "paid_at", "provider_reference"])
    return payment


def cancel_pending_payments(order):
    order.payments.filter(status=Payment.Status.PENDING).update(status=Payment.Status.CANCELLED)
