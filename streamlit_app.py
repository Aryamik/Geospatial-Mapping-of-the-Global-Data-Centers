import streamlit as st
import folium
from streamlit_folium import st_folium
import requests
import xml.etree.ElementTree as ET
import pandas as pd
import os
import feedparser
from datetime import datetime
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer


st.set_page_config(
    page_title="Geospatial Mapping of Global Data Centers and Real Time Sentiment Analysis of Data Center Headlines",
    layout="wide"
)

st.title("Geospatial Mapping of Global Data Centers and Real Time Sentiment Analysis of Data Center Headlines")

st.markdown(
    """
    This dashboard combines [NASA’s Global Imagery Browse Services (GIBS)](https://nasa-gibs.github.io/gibs-api-docs/) with geocoded locations of [global data centers](https://raw.githubusercontent.com/Ringmast4r/Global-Data-Center-Map/main/datacenters.geojson) as well [Frontier data centers](https://epoch.ai/data/data-centers?view=graph&tab=power) (as of June 08, 2026). This application uses imagery provided by services from NASA's Global Imagery Browse Services (GIBS), part of NASA's Earth Science Data and Information System (ESDIS). This application also monitors the sentiment of real time news headlines related to data centers.  

    """
)

st.markdown(
    """
   **Disclaimer:** This application is provided for informational and research purposes only. While care has been taken to compile the data accurately, no guarantees are made regarding completeness, accuracy, or timeliness of the data.
    """
)
col1, col2 = st.columns([3, 1])

WMS_BASE_URL = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
CAPABILITIES_URL = f"{WMS_BASE_URL}?SERVICE=WMS&REQUEST=GetCapabilities"

NS = {"wms": "http://www.opengis.net/wms", "xlink": "http://www.w3.org/1999/xlink"}

@st.cache_data(show_spinner=True)
def load_wms_hierarchy():
    r = requests.get(CAPABILITIES_URL)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    top_layer = root.find("wms:Capability/wms:Layer", NS)

    def collect_layers(layer):
        out = []
        name = layer.find("wms:Name", NS)
        title = layer.find("wms:Title", NS)
        if name is not None:
            out.append({"name": name.text, "title": title.text if title is not None else name.text})
        for child in layer.findall("wms:Layer", NS):
            out.extend(collect_layers(child))
        return out

    hierarchy = {}
    for category in top_layer.findall("wms:Layer", NS):
        cat_title_el = category.find("wms:Title", NS)
        if cat_title_el is None:
            continue
        subcats = {}
        for subcat in category.findall("wms:Layer", NS):
            sub_title_el = subcat.find("wms:Title", NS)
            if sub_title_el is None:
                continue
            layers = collect_layers(subcat)
            if layers:
                subcats[sub_title_el.text] = layers
        if subcats:
            hierarchy[cat_title_el.text] = subcats
    return hierarchy

wms_hierarchy = load_wms_hierarchy()

GEOJSON_URL = "https://raw.githubusercontent.com/Ringmast4r/Global-Data-Center-Map/main/datacenters.geojson"

@st.cache_data(show_spinner=True)
def load_geojson():
    r = requests.get(GEOJSON_URL)
    r.raise_for_status()
    return r.json()

geo_data = load_geojson()

BASE_DIR = os.path.dirname(__file__)
CSV_PATH = os.path.join(BASE_DIR, "data", "AI data centers.csv")


@st.cache_data(show_spinner=True)
def load_frontier_csv():
    return pd.read_csv(CSV_PATH)

frontier_df = load_frontier_csv()

frontier_df["Latitude"] = pd.to_numeric(frontier_df["Latitude"], errors="coerce")
frontier_df["Longitude"] = pd.to_numeric(frontier_df["Longitude"], errors="coerce")
frontier_df = frontier_df.dropna(subset=["Latitude", "Longitude"])


#Map controls
countries = sorted({
    f["properties"].get("country", "")
    for f in geo_data["features"]
    if f["properties"].get("country")
})
country_filter = col1.selectbox("Filter by Country", ["All"] + countries)

if country_filter != "All":
    filtered_dcs = [
        f for f in geo_data["features"]
        if f["properties"].get("country") == country_filter
    ]
else:
    filtered_dcs = geo_data["features"]

dc_geojson = {
    "type": "FeatureCollection",
    "features": filtered_dcs
}


category = col1.selectbox("Category", sorted(wms_hierarchy))
subcategory = col1.selectbox("Sub-category", sorted(wms_hierarchy[category]))

layers = wms_hierarchy[category][subcategory]
if len(layers) == 1:
    layer_title = layers[0]["title"]
    layer_name = layers[0]["name"]
else:
    title_to_name = {l["title"]: l["name"] for l in layers}
    layer_title = col1.selectbox("Layer", sorted(title_to_name))
    layer_name = title_to_name[layer_title]


#mapping the layers - NASA's WMS, Global data centers GeoJSON and Frontier Data Centers
m = folium.Map(location=[20, 0], zoom_start=2, tiles="OpenStreetMap")

folium.WmsTileLayer(
    url=WMS_BASE_URL,
    name=layer_title,
    layers=layer_name,
    fmt="image/png",
    transparent=True,
    overlay=True,
    control=True
).add_to(m)

folium.GeoJson(
    dc_geojson,
    name="Data Centers",
    tooltip=folium.GeoJsonTooltip(
        fields=["name", "company", "city", "country"],
        aliases=["Name:", "Company:", "City:", "Country:"],
    ),
    popup=folium.GeoJsonPopup(
        fields=["name", "address", "company", "city", "country"]
    ),
    marker=folium.Marker(
        icon=folium.Icon(
            icon="server",
            prefix="fa",
            color="green"
        )
    )
).add_to(m)

frontier_group = folium.FeatureGroup(
    name="Frontier Data Centers"
)
for _, row in frontier_df.iterrows():
    folium.Marker(
        location=[row["Latitude"], row["Longitude"]],
        popup=f"<b>{row['Name']}</b>",
        tooltip=row["Name"],
        icon=folium.Icon(color="red", icon="bolt", prefix="fa")
    ).add_to(frontier_group)

frontier_group.add_to(m)

folium.LayerControl(collapsed=False).add_to(m)


col1_data = st_folium(m, width=1400, height=900)

#Data Center News Tracker
st.markdown("---")

#setting up the RSS url for Google News using the search term 'data center'
RSS_URL = "https://news.google.com/rss/search?q=data+center&hl=en"
analyzer = SentimentIntensityAnalyzer()


if "num_rows" not in st.session_state:
    st.session_state.num_rows = 25
if "articles" not in st.session_state:
    st.session_state.articles = pd.DataFrame()

PAGE_SIZE = 25
st.markdown("""
<style>
html, body, [class*="css"]  {
    font-family: 'Inter', 'Segoe UI', sans-serif;
}
</style>
""", unsafe_allow_html=True)


def fetch_news():
    feed = feedparser.parse(RSS_URL)
    rows = []

    for entry in feed.entries:
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            published = datetime(*entry.published_parsed[:6])
            ts = published.strftime("%Y-%m-%d %H:%M")
        else:
            ts = ""

        title = entry.title

        score = analyzer.polarity_scores(title)["compound"]

        if score >= 0.05:
            sentiment = "Positive"
            emoji = "🙂"
            color = "#2ecc71"
        elif score <= -0.05:
            sentiment = "Negative"
            emoji = "☹️"
            color = "#e74c3c"
        else:
            sentiment = "Neutral"
            emoji = "😐"
            color = "#f1c40f"

        rows.append({
            "Headline": title,
            "Source": entry.get("source", {}).get("title") or "Google News",
            "Timestamp": ts,
            "Sentiment": sentiment,
            "Emoji": emoji,
            "Link": entry.link,
            "Color": color
        })

    df = pd.DataFrame(rows)
    df.sort_values("Timestamp", ascending=False, inplace=True)
    return df


new_articles = fetch_news()
if st.session_state.articles.empty:
    st.session_state.articles = new_articles
else:
    existing_links = set(st.session_state.articles['Link'])
    new_to_add = new_articles[~new_articles['Link'].isin(existing_links)]
    if not new_to_add.empty:
        st.session_state.articles = pd.concat(
            [new_to_add, st.session_state.articles],
            ignore_index=True
        )

df = st.session_state.articles
ticker_text = "   •   ".join(df["Headline"].head(20).tolist())

ticker_html = f"""
<style>
.ticker-container {{
    background: #0e1117;
    padding: 10px;
    border-radius: 10px;
    overflow: hidden;
    border: 1px solid #2a2a2a;
}}

.ticker {{
    display: inline-block;
    white-space: nowrap;
    padding-left: 100%;
    animation: scroll 300s linear infinite;
    font-size: 16px;
    font-family: 'Inter', 'Segoe UI', sans-serif;
    color: #ffd700;
}}

@keyframes scroll {{
    0% {{ transform: translateX(0); }}
    100% {{ transform: translateX(-100%); }}
}}
</style>

<div class="ticker-container">
    <div class="ticker">{ticker_text}</div>
</div>
"""

st.components.v1.html(ticker_html, height=55)


def render_table(df):
    html = """
    <style>
        .table-container {
            max-height: 600px;
            overflow-y: auto;
            border: 1px solid #2a2a2a;
            border-radius: 8px;
        }
        table {
            width:100%;
            border-collapse: collapse;
            font-family: 'Inter', 'Segoe UI', sans-serif;
        }
        th, td {
            font-family: 'Inter', 'Segoe UI', sans-serif;
            font-weight: 500;
        }
        th {
            background:#111;
            color:white;
            padding:10px;
            text-align:left;
            position: sticky;
            top: 0;
        }
        td {
            padding:10px;
            border-bottom:1px solid #2a2a2a;
            color:#ddd;
            vertical-align: middle;
        }
        a { color:#4da3ff; text-decoration:none; }
        .badge {
            padding:5px 10px;
            border-radius:8px;
            color:white;
            font-weight:600;
            font-family:'Inter', 'Segoe UI', sans-serif;
            display:inline-block;
        }
    </style>

    <div class="table-container">
    <table>
        <tr>
            <th>Headline</th>
            <th>Sentiment</th>
            <th>Source</th>
            <th>Time</th>
        </tr>
    """
    for _, row in df.iterrows():
        sentiment_label = f"{row['Emoji']} {row['Sentiment']}"
        html += f"""
        <tr>
            <td><a href="{row['Link']}" target="_blank">{row['Headline']}</a></td>
            <td><span class="badge" style="background:{row['Color']}">{sentiment_label}</span></td>
            <td>{row['Source']}</td>
            <td>{row['Timestamp']}</td>
        </tr>
        """
    html += "</table></div>"
    return html


table_container = st.container()
with table_container:
    df_page = df.iloc[:st.session_state.num_rows]
    st.components.v1.html(render_table(df_page), height=600)

if st.button("Load More"):
    st.session_state.num_rows = min(
        st.session_state.num_rows + PAGE_SIZE,
        len(df)
    )
    st.rerun()

