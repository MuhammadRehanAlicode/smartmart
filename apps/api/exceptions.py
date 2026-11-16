from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.views import exception_handler


class BusinessRuleError(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "The request breaks a business rule."
    default_code = "business_rule"


class StockConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Not enough stock."
    default_code = "insufficient_stock"


def api_exception_handler(exc, context):
    """Every API error looks like {"error": {"status", "code", "message", "details"}}."""
    response = exception_handler(exc, context)
    if response is None:
        return None
    code = getattr(exc, "default_code", "error")
    details = None
    if isinstance(exc, ValidationError):
        message, details = "The submitted data is not valid.", response.data
    elif isinstance(response.data, dict) and "detail" in response.data:
        message = str(response.data["detail"])
    else:
        message = "The request could not be completed."
    response.data = {"error": {"status": response.status_code, "code": code, "message": message, "details": details}}
    return response
