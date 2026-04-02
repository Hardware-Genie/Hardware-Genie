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

        print(df['deal_quality'])
        
        plt.hist(df['value'], bins = 20, edgecolor = 'black')
        plt.title(capacity)
        plt.show()

    return results
