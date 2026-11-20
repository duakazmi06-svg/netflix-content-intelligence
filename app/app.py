import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

import palette as pal

st.set_page_config(page_title="Netflix Content Intelligence", layout="wide")

st.markdown(
    f"""
    <style>
     /* Card-style tabs */
    div[data-baseweb="tab-list"],
    [data-testid="stTabs"] [role="tablist"] {{
        gap: 16px !important;
        background: transparent !important;
        padding: 8px 0 !important;
    }}

    button[role="tab"],
    button[data-baseweb="tab"],
    [data-testid="stTab"] {{
        background-color: {pal.CARD} !important;
        border: 1px solid {pal.BORDER} !important;
        border-left: 4px solid {pal.NETFLIX_RED} !important;
        border-radius: 10px !important;
        padding: 14px 36px !important;
        height: auto !important;
        min-width: 140px;
        justify-content: center;
    }}

    button[role="tab"] p,
    button[role="tab"] span,
    [data-testid="stTab"] p {{
        color: white !important;
        font-size: 18px !important;
        font-weight: 600 !important;
    }}

    button[role="tab"]:hover,
    [data-testid="stTab"]:hover {{
        background-color: {pal.BORDER} !important;
    }}

    button[role="tab"][aria-selected="true"],
    [data-testid="stTab"][aria-selected="true"] {{
        background-color: {pal.NETFLIX_RED} !important;
        border: 1px solid {pal.NETFLIX_RED} !important;
    }}

    /* hide the default underline */
    [data-baseweb="tab-highlight"],
    [data-baseweb="tab-border"] {{
        display: none !important;
    }}

    /* Existing dashboard styling */
    .stApp {{ background: linear-gradient(180deg, {pal.BG_TOP} 0%, {pal.BG_BOTTOM} 100%); background-attachment: fixed; }}

    [data-testid="stSidebar"] {{
        background-color: {pal.BG_SIDEBAR};
        border-right: 1px solid {pal.BORDER};
    }}

    [data-testid="stMetric"] {{
        background-color: {pal.CARD};
        border-left: 4px solid {pal.NETFLIX_RED};
        padding: 12px 16px;
        border-radius: 6px;
    }}

    [data-testid="stMetricLabel"] {{ color: {pal.GREY}; }}

    h1, h2, h3 {{ letter-spacing: 0.5px; }}
    hr {{ border-color: {pal.BORDER}; }}
    </style>
    """,
    unsafe_allow_html=True,
)


def find_db():
    here = Path(__file__).resolve().parent
    for folder in [here, here.parent, here / "data", here.parent / "data"]:
        p = folder / "netflix_analysis.db"
        if p.exists():
            return p
    st.error("netflix_analysis.db not found. Place in project folder.")
    st.stop()


@st.cache_data
def load_table(name):
    con = sqlite3.connect(find_db())
    df = pd.read_sql_query(f"SELECT * FROM {name}", con)
    con.close()
    return df


def style(fig):
    fig.update_traces(marker_color=pal.NETFLIX_RED)
    fig.update_layout(
        plot_bgcolor=pal.CHART_BG,
        paper_bgcolor=pal.CHART_BG,
        font_color=pal.WHITE,
        margin=dict(l=10, r=10, t=10, b=10),
    )
    fig.update_xaxes(gridcolor=pal.BORDER, zerolinecolor=pal.BORDER)
    fig.update_yaxes(gridcolor=pal.BORDER, zerolinecolor=pal.BORDER)
    return fig


def counts(series, label, n=10):
    return series.value_counts().head(n).rename_axis(label).reset_index(name="total")


titles = load_table("titles")
genres = load_table("genres")
title_genres = load_table("title_genres")
countries = load_table("countries")
availability = load_table("title_availability")

# ---------- Sidebar filters ----------
st.sidebar.header("Filters")
media_options = sorted(titles["media_type"].dropna().unique())
media_sel = st.sidebar.multiselect("Type", media_options, default=media_options)

years = titles["release_year"].dropna().astype(int)
y_min, y_max = int(years.min()), int(years.max())
year_range = st.sidebar.slider("Release year", y_min, y_max, (y_min, y_max))

f = titles[
    titles["media_type"].isin(media_sel)
    & titles["release_year"].between(year_range[0], year_range[1])
]
ids = f["title_id"]

# ---------- Header ----------
st.markdown(
    f"<h1 style='color:{pal.NETFLIX_RED}'>Netflix Content Intelligence</h1>",
    unsafe_allow_html=True,
)
st.caption("Data source: netflix_analysis.db")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Titles", f"{len(f):,}")
c2.metric("Average rating", f"{f['vote_average'].mean():.2f}" if len(f) else "-")
c3.metric("Countries", countries[countries["title_id"].isin(ids)]["country"].nunique())
c4.metric("Languages", f["language"].nunique())

st.divider()

# ---------- Tabs ----------
tab1, tab2, tab3 = st.tabs(["Overview", "Trend", "Table"])

with tab1:
    left, right = st.columns(2)

    with right:
        st.subheader("Movies vs TV shows")
        mt = counts(f["media_type"], "media_type")
        fig = px.pie(
            mt,
            names="media_type",
            values="total",
            color="media_type",
            color_discrete_map={"movie": pal.PIE_RED, "tv": pal.PIE_WHITE},
        )
        fig.update_layout(
            paper_bgcolor=pal.CHART_BG,
            font_color=pal.WHITE,
            margin=dict(l=10, r=10, t=10, b=10),
        )
        fig.update_traces(
            marker=dict(line=dict(color="#1A0507", width=2)),
            textfont=dict(
                color=["#FFFFFF" if m == "movie" else "#141414" for m in mt["media_type"]],
                size=16,
            ),
        )
        st.plotly_chart(fig, use_container_width=True)

    with left:
        st.subheader("Top 10 genres")
        g = title_genres[title_genres["title_id"].isin(ids)].merge(genres, on="genre_id")
        fig = px.bar(counts(g["genre_name"], "genre"), x="genre", y="total")
        st.plotly_chart(style(fig), use_container_width=True)

    left, right = st.columns(2)

    with left:
        st.subheader("Top 10 countries")
        c = countries[countries["title_id"].isin(ids) & (countries["country"] != "Unknown")]
        fig = px.bar(counts(c["country"], "country"), x="country", y="total")
        st.plotly_chart(style(fig), use_container_width=True)

    with right:
        st.subheader("Top 10 languages")
        fig = px.bar(counts(f["language"], "language"), x="language", y="total")
        st.plotly_chart(style(fig), use_container_width=True)

    st.subheader("Rating distribution")
    fig = px.histogram(f, x="vote_average", nbins=20)
    fig = style(fig)
    fig.update_traces(marker_line_color=pal.BORDER, marker_line_width=1)
    st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.subheader("Titles released per year")
    per_year = (
        f.dropna(subset=["release_year"])
        .assign(release_year=lambda d: d["release_year"].astype(int))
        .groupby(["release_year", "media_type"])
        .size()
        .reset_index(name="total")
    )
    fig = px.line(
        per_year,
        x="release_year",
        y="total",
        color="media_type",
        color_discrete_map={"movie": pal.PIE_RED, "tv": pal.PIE_WHITE},
    )
    fig.update_layout(
        plot_bgcolor=pal.CHART_BG,
        paper_bgcolor=pal.CHART_BG,
        font_color=pal.WHITE,
        margin=dict(l=10, r=10, t=10, b=10),
    )
    fig.update_xaxes(gridcolor=pal.BORDER, zerolinecolor=pal.BORDER)
    fig.update_yaxes(gridcolor=pal.BORDER, zerolinecolor=pal.BORDER)
    st.plotly_chart(fig, use_container_width=True)

with tab3:
    st.subheader("Top rated titles")
    top = (
        f[f["vote_count"] >= 50]
        .sort_values("vote_average", ascending=False)
        .head(10)[["title", "media_type", "release_year", "language", "vote_average", "vote_count"]]
    )
    st.dataframe(top, use_container_width=True, hide_index=True)
