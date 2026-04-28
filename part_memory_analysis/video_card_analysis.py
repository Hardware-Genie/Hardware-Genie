# List of columns to add when displaying on website
# "Chipset" which can be called from ["chipset"]

import pandas as pd

df = pd.read_csv("combined_video-card.csv")
df = df.dropna(subset=["price", "memory", "core_clock", "boost_clock"])

df["price_float"] = df["price"].astype(float)
df["memory_float"] = df["memory"].astype(float)
df["core_clock_float"] = df["core_clock"].astype(float)
df["boost_clock_float"] = df["boost_clock"].astype(float)

gpu_groups = {
    chipset: group
    for chipset, group in df.groupby(["chipset"])
}

def analyze_gpu_groups(groups):
    results = {}

    for key, df in groups.items():
        df = df.copy()

        df["quality"] = (
            df["memory_float"] *
            (df["core_clock_float"] + df["boost_clock_float"]) / 2
        )

        df["value"] = df["quality"] / df["price_float"]

        mean_value = df["value"].mean()
        df["deal_quality"] = df["value"].apply(
            lambda x: "Good Deal" if x >= mean_value else "Bad Deal"
        )

        results[key] = df

    return results


results = analyze_gpu_groups(gpu_groups)
