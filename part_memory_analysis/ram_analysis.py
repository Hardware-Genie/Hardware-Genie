import pandas as pd
import matplotlib.pyplot as plt
import re

# Load the CSV and drop any nonexistent values
df = pd.read_csv("static/data/old PCpartpicker data/combined_memory.csv")
df = df.dropna()

# Function to extract the RAM size
def get_ram_size(name):
    match = re.search(r'(\d+)\s\s*GB', name)
    return int(match.group(1)) if match else None

# Create a new column with RAM size
df["ram_gb"] = df["name"].apply(get_ram_size)

# Create separate lists for each unique RAM amount
ram_lists = {
    size: group
    for size, group in df.groupby("ram_gb")
}

def analyze_ram_groups_hist(groups):
    results = {}

    for capacity, df in groups.items():
        df = df.copy()  # avoid modifying original

        # Convert speed column safely (handle comma decimals)
        df['speed_float'] = df['speed'].str.replace(', ', ',', regex=False)
        df['speed_float'] = df['speed_float'].str.replace(',', '.', regex=False).astype(float)

        # Ensure price column is float
        df['price_float'] = df['price'].astype(float)

        # Calculate quality and value
        df['quality'] = df['speed_float'] * capacity
        df['value'] = df['quality'] / df['price_float']
        
        # Compare values of components to the mean to determine deal quality
        mean_value = df['value'].mean()
        df['deal_quality'] = df['value'].apply(lambda x: "Good Deal" if x >= mean_value else "Bad Deal")

        # Store full DataFrame with new columns
        results[capacity] = df

    return results
