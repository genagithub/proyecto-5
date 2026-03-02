import sqlite3
import pandas as pd
from itertools import combinations
from collections import Counter
import plotly.express as px
import dash
from dash import html, dcc
from dash.dependencies import Input, Output


with sqlite3.connect("data/e-commerce.db") as conn:
    query = '''select oi.order_id, oi.product_id, p.category, p.retail_price, p.name as product_name from order_items oi
               join products p on oi.product_id = p.product_id'''
    df = pd.read_sql_query(query, conn)

categories_orders = df.groupby("order_id")["category"].apply(list)

multiples_orders = categories_orders[categories_orders.apply(len) > 1]

frequent_pairs = Counter()

for categories in multiples_orders:
    comb = combinations(sorted(categories), 2)
    frequent_pairs.update(comb)

df_bundles = pd.DataFrame(frequent_pairs.most_common(10), columns=["categories_bundle", "historic_frequence"])

total_multiples_orders = len(multiples_orders)

df_bundles["relevance_%"] = round((df_bundles["historic_frequence"] / total_multiples_orders) * 100, 2)

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 1000)

with sqlite3.connect("data/e-commerce.db") as conn:
    prices_query = 'select category, avg(retail_price) as mean_price from products group by category'
    df_prices = pd.read_sql_query(prices_query, conn)


dict_prices = dict(zip(df_prices["category"], df_prices["mean_price"]))

def calculate_bundle_price(categories_pair, prices):
    cat1, cat2 = categories_pair
    return prices.get(cat1, 0) + prices.get(cat2, 0)

df_bundles["original_price_combo"] = df_bundles["categories_bundle"].apply(lambda x: calculate_bundle_price(x, dict_prices))

order_counts = df.groupby("order_id")["category"].transform("count")
individual_customers = df[order_counts == 1]["category"].value_counts().to_dict()

def simulate_real_uplift(row, dict_individuals, migration_rate=0.03, desc=0.15):
    cat1, cat2 = row["categories_bundle"]
    base_price = row["original_price_combo"]
    frequence = row["historic_frequence"]
    
    pot_cat1 = dict_individuals.get(cat1, 0)
    pot_cat2 = dict_individuals.get(cat2, 0)
    potential_market = min(pot_cat1, pot_cat2) 
    
    cannibalization_loss = frequence * (base_price * desc)
    
    new_sales = potential_market * migration_rate
    new_income = new_sales * (base_price * (1 - desc))
    
    uplift_neto = new_income - cannibalization_loss
    
    return round(uplift_neto, 2), int(new_sales)

results = df_bundles.apply(lambda row: simulate_real_uplift(row, individual_customers), axis=1)
df_bundles[["final_uplift_USD", "new_estimates_customers"]] = pd.DataFrame(results.tolist(), index=df_bundles.index)

all_categories = [item for sublist in df_bundles["categories_bundle"] for item in sublist]
unique_candidates = sorted(list(set(all_categories)))
dropdown_options = [{"label": cat, "value": cat} for cat in unique_candidates]

uplift = html.B(children=[], id="uplift")
breakeven_rate = html.B(children=[], id="breakeven_rate", style={"font-size":"0.9em"})
AOV = html.B(children=[], id="AOV")

app = dash.Dash(__name__)
server = app.server

app.layout = html.Div(id="body", className="e5_body", children=[
    html.H1("Estimación de Uplift mediante enfoque de Bundling", id="title", className="e5_title"),
    html.Div(id="container_1", className="e5_container_1",children=[
        html.Div(id="dropdown_div", className="e5_dropdown_div", children=[
            dcc.Dropdown(id="dropdown", className="e5_dropdown", 
            options=dropdown_options,
            value=unique_candidates[0],
            multi=False,
            clearable=False)
        ]),
        html.Div(id="div",className="e5_div",style={"margin-right":"25px"},children=[
            html.Div(className="e5_KPI_div", style={"width":"175px","height":"40px"}, children=[html.P("Uplift", className="e5_KPI_title", style={"font-size":"1em"}), html.P(uplift, className="e5_KPI")]),
            html.Div(className="e5_KPI_div", style={"width":"175px","height":"40px"}, children=[html.P("Breakeven Rate", className="e5_KPI_title", style={"font-size":"0.9em"}), html.P(breakeven_rate, className="e5_KPI")]),
            html.Div(className="e5_KPI_div", style={"width":"175px","height":"40px"}, children=[html.P("AOV", className="e5_KPI_title", style={"font-size":"1em"}), html.P(AOV, className="e5_KPI")])
        ])
    ]),
    html.Div(id="container_2", className="e5_container_2", style={"margin-bottom":"0"}, children=[
        dcc.Graph(id="donut_chart", figure={}, className="e5_graph_1", style={"width":"300px","height":"300px"}),
        dcc.Graph(id="barplot", figure={}, className="e5_graph_2", style={"width":"850px","height":"300px"})    
    ])
])


@app.callback(
    [Output(component_id="uplift",component_property="children"),
    Output(component_id="breakeven_rate",component_property="children"),
    Output(component_id="AOV",component_property="children"),
    Output(component_id="donut_chart",component_property="figure"),
    Output(component_id="barplot",component_property="figure")],
    [Input(component_id="dropdown",component_property="value")])

def update_graph(slct_cat):
    mask = df_bundles["categories_bundle"].apply(lambda x: slct_cat in x)
    df_res = df_bundles[mask].sort_values(by="final_uplift_USD", ascending=False)

    if df_res.empty:
        return "$0.00", "0%", "$0.00", {}

    best_bundle = df_res.iloc[0]
    
    uplift_val = best_bundle["final_uplift_USD"]
    color_u = "#2ecc71" if uplift_val >= 0 else "#e74c3c"
    uplift = html.Span(f"{"+" if uplift_val > 0 else ""}${uplift_val:,.0f}", style={"color": color_u})
    
    aov_bundle = best_bundle["original_price_combo"] * 0.85
    
    cat1, cat2 = best_bundle["categories_bundle"]
    pot_cat1 = individual_customers.get(cat1, 0)
    pot_cat2 = individual_customers.get(cat2, 0)
    potential_market = min(pot_cat1, pot_cat2)
    
    price_with_desc = best_bundle["original_price_combo"] * (1 - 0.15)
    cannibalization = best_bundle["historic_frequence"] * (best_bundle["original_price_combo"] * 0.15)
    
    if (potential_market * price_with_desc) > 0:
        breakeven_rate = (cannibalization / (potential_market * price_with_desc)) * 100
    else:
        breakeven_rate = 0
    
    filtered_df = df[df["category"] == slct_cat]

    product_sales = filtered_df.groupby("product_name")["retail_price"].sum().reset_index()
    product_sales = product_sales.sort_values(by="retail_price", ascending=False).head(10)
    
    donut_chart = px.pie(
        product_sales, 
        values="retail_price", 
        names="product_name", 
        hole=0.6,
        title=f"Top productos en {slct_cat}",
        color_discrete_sequence=px.colors.sequential.RdBu 
    )
    
    donut_chart.update_layout(
        showlegend=False,
        margin=dict(t=40, b=0, l=0, r=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="black")
    )
    
    df_assoc = df_bundles[mask].copy()

    if df_assoc.empty:
        return "N/A", "N/A", "N/A", {}, {}

    df_assoc["partner"] = df_assoc["categories_bundle"].apply(lambda x: x[1] if x[0] == slct_cat else x[0])
    
    df_assoc = df_assoc.sort_values(by="relevance_%", ascending=False).head(5)

    barplot = px.bar(
        df_assoc,
        x="partner",
        y="relevance_%",
        text="relevance_%",
        title=f"Categorías con mayor afinidad a {slct_cat}",
        color="relevance_%",
        color_continuous_scale="Viridis" 
    )

    barplot.update_traces(
        texttemplate="%{text:.1f}%", 
        textposition="outside",
        marker_line_color="#ffffff",
        marker_line_width=1.5,
        opacity=0.85,
        marker_color="#2c3e50"
    )

    barplot.update_layout(
        font=dict(color="#2c3e50", family="Arial, sans-serif"),
        title=dict(font=dict(size=18, color="#1a252f"), x=0.05),
        xaxis=dict(title="", showgrid=False, linecolor="#bdc3c7"),
        yaxis=dict(title="Relevancia (%)", showgrid=True, gridcolor="#ecf0f1", range=[0, df_assoc["relevance_%"].max() * 1.2] ),
        coloraxis_showscale=False, 
        margin=dict(t=60, b=40, l=40, r=20),
        hovermode="x unified"
    )
    
    return uplift, f"{breakeven_rate:.2f}% Min. Conv.",  f"$ {aov_bundle:,.2f}", donut_chart, barplot

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050)) 
    app.run_server(host='0.0.0.0', port=port)
