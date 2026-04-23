# List of columns to add when displaying on website
# "Number of Memory Slots" which can be called from ["memory_slots"]
# "Socket Type" which can be called from ["socket"]
# "Form Factor" which can be called from ["form_factor6"]

import pandas as pd

df = pd.read_csv("combined_motherboard.csv")
df = df.dropna()

df["price_float"] = df["price"].astype(float)
df["max_memory_float"] = df["max_memory"].astype(float)

motherboard_groups = {
    (socket, form_factor, max_mem): group
    for (socket, form_factor, max_mem), group in df.groupby(
        ["socket", "form_factor", "max_memory_float"]
    )
}

def analyze_motherboard_groups(groups):
    results = {}

    for key, df in groups.items():
        df = df.copy()

        df["quality"] = df["max_memory_float"]

        # Value metric
        df["value"] = df["quality"] / df["price_float"]

        mean_value = df["value"].mean()
        df["deal_quality"] = df["value"].apply(
            lambda x: "Good Deal" if x >= mean_value else "Bad Deal"
        )

        results[key] = df

    return results
