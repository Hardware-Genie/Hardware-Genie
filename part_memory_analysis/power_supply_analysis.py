# 

import pandas as pd
import re

# Load the CSV and drop any nonexistent values
df = pd.read_csv("combined_power-supply.csv")

# Function to extract/normalize efficiency tier
def get_efficiency_tier(eff):
    if pd.isna(eff):
        return "plus"
    
    eff = eff.lower().strip()
    
    # Normalize possible variations
    if "titanium" in eff:
        return "titanium"
    elif "platinum" in eff:
        return "platinum"
    elif "gold" in eff:
        return "gold"
    elif "silver" in eff:
        return "silver"
    elif "bronze" in eff:
        return "bronze"
    else:
        return "plus"  # fallback / unknown

# Apply normalization
df["efficiency_tier"] = df["efficiency"].apply(get_efficiency_tier)

# Mapping based on 80 PLUS chart (50% load typical)
efficiency_map = {
    "plus": 80,
    "bronze": 85,
    "silver": 88,
    "gold": 90,
    "platinum": 92,
    "titanium": 94
}

# Create numeric efficiency column
df["efficiency_numeric"] = df["efficiency_tier"].map(efficiency_map)

# Create separate lists for each efficiency tier
efficiency_lists = {
    tier: group
    for tier, group in df.groupby("efficiency_tier")
}

def analyze_efficiency_groups(groups):
    results = {}

    for tier, df in groups.items():
        df = df.copy()  # avoid modifying original

        # Ensure numeric columns
        df["price_float"] = df["price"].astype(float)
        df["wattage_float"] = df["wattage"].astype(float)

        # Example "quality" metric: efficiency * wattage
        df["quality"] = df["efficiency_numeric"] * df["wattage_float"]

        # Value metric
        df["value"] = df["quality"] / df["price_float"]

        # Compare to group mean
        mean_value = df["value"].mean()
        df["deal_quality"] = df["value"].apply(
            lambda x: "Good Deal" if x >= mean_value else "Bad Deal"
        )

        results[tier] = df

    return results
