# List of columns to add when displaying on website
# "Number of Cores" which can be called from ["core_count"]
# "Integrated Graphics" which can be called from ["graphics_status"]
# "Boost Ability" which can be called from ["boost_status"]

import pandas as pd
import re

# Load the CSV and drop any nonexistent values
df = pd.read_csv("combined_cpu.csv")

def get_boost_status(eff):
    if pd.isna(eff):
        return "No"
    else:
        return "Yes"
        
    eff = eff.lower().strip()

df["boost_status"] = df["boost_clock"].apply(get_boost_status)
    
def get_graphics_status(eff):
    if pd.isna(eff):
        return "No"
    else:
        return "Yes"
        
    eff = eff.lower().strip()

df["graphics_status"] = df["graphics"].apply(get_boost_status)

efficiency_lists = {
    tier: group
    for tier, group in df.groupby("core_count")
}

def analyze_cpu_groups(groups):
    results = {}

    for tier, df in groups.items():
        df = df.copy()  # avoid modifying original

        df["price_float"] = df["price"].astype(float)
        df["core_float"] = df["core_count"].astype(float)
        df["clock_float"] = df["core_clock"].astype(float)
        df["tdp_float"] = df["tdp"].astype(float)

        df["quality"] = df["core_float"] * df["clock_float"] * df["tdp_float"]
        df["value"] = df["quality"] / df["price_float"]\

        mean_value = df["value"].mean()
        df["deal_quality"] = df["value"].apply(
            lambda x: "Good Deal" if x >= mean_value else "Bad Deal"
        )

        results[tier] = df

    return results
