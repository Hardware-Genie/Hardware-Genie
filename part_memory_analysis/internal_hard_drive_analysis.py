# List of columns to add when displaying on website
# "Type of Storage" which can be called from ["type"]
# "Form Factor" which can be called from ["form_factor"]

df = pd.read_csv("combined_internal-hard-drive.csv")
df = df.dropna(subset=["price", "capacity"])

df["price_float"] = df["price"].astype(float)
df["capacity_float"] = df["capacity"].astype(float)

df["cache"] = pd.to_numeric(df["cache"], errors="coerce")
df["cache"] = df["cache"].fillna(df["cache"].median())

storage_groups = {
    (dtype, form): group
    for (dtype, form), group in df.groupby(["type", "form_factor"])
}

def analyze_storage_groups(groups):
    results = {}

    for key, df in groups.items():
        df = df.copy()

        df["quality"] = df["capacity_float"] * (1 + df["cache"] / 256)
        df["value"] = df["quality"] / df["price_float"]

        mean_value = df["value"].mean()
        df["deal_quality"] = df["value"].apply(
            lambda x: "Good Deal" if x >= mean_value else "Bad Deal"
        )

        results[key] = df

    return results


results = analyze_storage_groups(storage_groups)
