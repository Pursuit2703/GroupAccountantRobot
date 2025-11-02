from bot.config import CURRENCY

def format_amount(amount: float) -> str:
    # Round to 3 decimal places for precision up to thousandths
    # and to handle cases like .99999 -> 1
    # Then format with a comma for thousands.
    # Finally, strip trailing zeros and the decimal point if not needed.
    formatted_number = f"{amount:,.3f}".rstrip('0').rstrip('.')
    return f"{formatted_number} {CURRENCY}"