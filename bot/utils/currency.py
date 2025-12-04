from bot.config import CURRENCY

def format_amount(amount: float) -> str:
    # Round to 5 decimal places to match the database precision (u5)
    # and to handle cases like .99999 -> 1
    # Then format with a comma for thousands.
    # Finally, strip trailing zeros and the decimal point if not needed.
    formatted_number = f"{amount:,.5f}".rstrip('0').rstrip('.')
    return f"{formatted_number} {CURRENCY}"