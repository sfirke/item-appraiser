"""How a model's three guesses become dollars and kg CO2e. No API key needed."""

from item_appraiser import (
    Condition, FootprintCategory, ResaleDemand,
    buy_value, giveaway_kg_co2e, loan_kg_co2e, loan_value, new_item_kg_co2e,
)

# Suppose the model said: a used iPhone 11 would cost $400 new, resale demand is typical.
new_price = 400.0
buy = buy_value(new_price, Condition.USED, ResaleDemand.TYPICAL)  # 400 x 0.6
loan = loan_value(buy)                                            # half of first $50 + a quarter of the rest
kg_new = new_item_kg_co2e(new_price, FootprintCategory.SMARTPHONE)  # fixed per-phone footprint
print(f"Giveaway value ${buy:.2f}, loan value ${loan:.2f}")
print(f"Footprint new {kg_new} kg; giveaway avoids {giveaway_kg_co2e(kg_new, Condition.USED)} kg; "
      f"each loan avoids {loan_kg_co2e(kg_new)} kg")
