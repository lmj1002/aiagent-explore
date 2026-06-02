---
name: data-analysis
description: Common pandas and matplotlib patterns for data analysis and visualization. Use when the user asks to analyze CSV data, compute statistics, create charts, or generate data reports.
---

# Data Analysis Skill

## 1. Data Loading

### Reading CSV Files

```python
import pandas as pd

df = pd.read_csv("sales_data.csv")
```

### Quick Data Inspection

```python
df.info()              # Column types, non-null counts
df.describe()          # Summary statistics (count, mean, std, min, max)
df.head(10)            # First 10 rows
df.columns.tolist()    # Column names list
df.dtypes              # Data types per column
```

### Handling Missing Values

```python
df.isnull().sum()                    # Count missing per column
df.dropna()                           # Drop rows with any missing value
df.fillna(value={"col": 0})           # Fill missing with a default
```

### Type Conversion

```python
df["Date"] = pd.to_datetime(df["Date"])   # String to datetime
df["Units Sold"] = pd.to_numeric(df["Units Sold"], errors="coerce")
df["Revenue"] = pd.to_numeric(df["Revenue"], errors="coerce")
```

## 2. Data Aggregation

### Group By

```python
# Total units sold per product
product_sales = df.groupby("Product")["Units Sold"].sum()

# Total revenue per product
product_revenue = df.groupby("Product")["Revenue"].sum()

# Multiple aggregations
summary = df.groupby("Product").agg(
    total_units=("Units Sold", "sum"),
    total_revenue=("Revenue", "sum"),
    avg_revenue=("Revenue", "mean"),
    count=("Revenue", "count"),
)
```

### Pivot Table

```python
pivot = df.pivot_table(
    values="Revenue",
    index="Date",
    columns="Product",
    aggfunc="sum",
    fill_value=0,
)
```

### Date-Based Aggregation

```python
# Ensure date column is datetime
df["Date"] = pd.to_datetime(df["Date"])

# Sales by day
daily = df.groupby("Date")["Revenue"].sum()

# Sales by month
df["Month"] = df["Date"].dt.to_period("M")
monthly = df.groupby("Month")["Revenue"].sum()
```

## 3. Visualization

### Matplotlib Setup

```python
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend for server/script use
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# Try to set a Chinese-supporting font
for name in ("Microsoft YaHei", "SimHei", "WenQuanYi Micro Hei"):
    for f in fm.fontManager.ttflist:
        if f.name == name:
            plt.rcParams["font.family"] = f.name
            break
plt.rcParams["axes.unicode_minus"] = False
```

### Bar Chart

```python
def plot_bar_chart(data, title, xlabel, ylabel, output_path):
    """Plot a bar chart and save to file."""
    fig, ax = plt.subplots(figsize=(10, 6))
    data.plot(kind="bar", ax=ax, color="steelblue", edgecolor="black")
    ax.set_title(title, fontsize=14)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.tick_params(axis="x", rotation=45)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    return output_path
```

### Line Chart

```python
def plot_line_chart(data, title, xlabel, ylabel, output_path):
    """Plot a line chart and save to file."""
    fig, ax = plt.subplots(figsize=(12, 5))
    data.plot(kind="line", marker="o", ax=ax, color="coral", linewidth=2)
    ax.set_title(title, fontsize=14)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True, linestyle="--", alpha=0.6)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    return output_path
```

### Pie Chart

```python
def plot_pie_chart(data, title, output_path):
    """Plot a pie chart and save to file."""
    fig, ax = plt.subplots(figsize=(8, 8))
    data.plot(kind="pie", autopct="%1.1f%%", ax=ax, startangle=90)
    ax.set_ylabel("")
    ax.set_title(title, fontsize=14)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    return output_path
```

### Seaborn Charts (if available)

```python
# import seaborn as sns

# Box plot
# sns.boxplot(x="Product", y="Revenue", data=df)

# Heatmap (correlation)
# numeric_df = df.select_dtypes(include="number")
# sns.heatmap(numeric_df.corr(), annot=True, cmap="coolwarm")

# Pair plot
# sns.pairplot(df)
```

## 4. Report Writing

### Writing Analysis Results

Use `write_file()` to save analysis findings as a Markdown report:

```python
report = f"""# Sales Data Analysis Report

## Summary
- Total Revenue: ${total_revenue:,.2f}
- Total Units Sold: {total_units}
- Number of Products: {num_products}

## Product Breakdown

| Product | Units Sold | Revenue |
|---------|-----------|---------|
{product_rows}

## Key Insights
{insights}

## Charts
![Sales Breakdown](sales_breakdown.png)
"""

# write_file("report.md", report)
```

### Recommended Report Structure

1. **Executive Summary** — Key metrics and top-level findings
2. **Data Overview** — Dataset shape, columns, data types
3. **Product Analysis** — Per-product breakdown with numbers
4. **Trend Analysis** — Time-based patterns (if date data available)
5. **Visualizations** — Charts embedded as images
6. **Conclusions & Recommendations** — Actionable insights

## 5. Common Analysis Patterns

### Top N Products by Revenue

```python
top_products = (
    df.groupby("Product")["Revenue"]
    .sum()
    .sort_values(ascending=False)
    .head(5)
)
```

### Daily Revenue Trend

```python
daily_revenue = df.groupby("Date")["Revenue"].sum()
```

### Product Contribution Percentage

```python
total = df["Revenue"].sum()
product_share = df.groupby("Product")["Revenue"].sum() / total * 100
```

## 6. Best Practices

- **Close figures**: Always call `plt.close()` after saving to free memory
- **Use `bbox_inches="tight"`** when saving to avoid cropped labels
- **Set DPI**: `dpi=150` for good quality without oversized files
- **Check data types**: Call `df.dtypes` before aggregation to avoid subtle errors
- **Sort grouped results**: Use `.sort_values(ascending=False)` for readable output
- **Handle edge cases**: Check for empty DataFrames before plotting
