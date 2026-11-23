import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
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


def kde_curve(values, grid):
    """Smooth density curve (same idea as seaborn kdeplot), no scipy needed."""
    v = np.asarray(values, dtype=float)
    v = v[~np.isnan(v)]
    if len(v) < 2:
        return None
    bw = 1.06 * v.std() * len(v) ** (-1 / 5)
    if bw == 0:
        bw = 0.1
    z = (grid[:, None] - v[None, :]) / bw
    return np.exp(-0.5 * z ** 2).sum(axis=1) / (len(v) * bw * np.sqrt(2 * np.pi))


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
tab1, tab2, tab3, tab4 = st.tabs(["Overview", "Trend", "Ratings", "Table"])

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
    # Chart 7: Rating density, movies vs TV (smooth curves, like the notebook)
    st.subheader("Rating density: movies vs TV shows")
    grid = np.linspace(0, 10, 300)
    colors = {"movie": pal.PIE_RED, "tv": pal.PIE_WHITE}
    fig = go.Figure()
    for m in sorted(f["media_type"].dropna().unique()):
        y = kde_curve(f.loc[f["media_type"] == m, "vote_average"], grid)
        if y is None:
            continue
        fig.add_trace(
            go.Scatter(
                x=grid,
                y=y,
                mode="lines",
                name=m,
                fill="tozeroy",
                opacity=0.7,
                line=dict(color=colors.get(m, pal.NETFLIX_RED), width=2),
            )
        )
    fig.update_layout(
        plot_bgcolor=pal.CHART_BG,
        paper_bgcolor=pal.CHART_BG,
        font_color=pal.WHITE,
        margin=dict(l=10, r=10, t=10, b=10),
    )
    fig.update_xaxes(gridcolor=pal.BORDER, zerolinecolor=pal.BORDER, title="rating")
    fig.update_yaxes(gridcolor=pal.BORDER, zerolinecolor=pal.BORDER, title="density")
    st.plotly_chart(fig, use_container_width=True)

    rated = f["vote_average"].dropna()
    if len(rated):
        med = f.groupby("media_type")["vote_average"].median()
        med_text = ", ".join(f"{k}: {v:.2f}" for k, v in med.items())
        share = rated.between(6, 8).mean() * 100
        low = (rated < 5).mean() * 100
        high = (rated >= 8).mean() * 100
        lines = [
            f"- {share:.0f}% of titles are rated between 6 and 8, so most content sits in the middle-to-good range.",
            f"- Median rating by type: {med_text}.",
            f"- Only {low:.0f}% of titles score below 5, while {high:.0f}% score 8 or higher.",
        ]
        if len(med) == 2:
            top_t = med.idxmax()
            gap = med.max() - med.min()
            lines[1] += f" {top_t} titles are rated higher by {gap:.2f} points."
        st.markdown("**Insights**\n" + "\n".join(lines))

    # Chart 10: Popularity vs rating
    st.subheader("Popularity vs rating")
    pop_col = "popularity" if "popularity" in f.columns else "vote_count"
    d = f.dropna(subset=[pop_col, "vote_average"])
    fig = px.scatter(
        d,
        x=pop_col,
        y="vote_average",
        log_x=True,
        opacity=0.5,
        hover_data=["title"],
    )
    st.plotly_chart(style(fig), use_container_width=True)

    if len(d) > 2:
        r = d[pop_col].rank().corr(d["vote_average"].rank())
        strength = "weak" if abs(r) < 0.3 else "moderate" if abs(r) < 0.6 else "strong"
        direction = "positive" if r > 0 else "negative"
        cut = d[pop_col].quantile(0.9)
        top_avg = d[d[pop_col] >= cut]["vote_average"].mean()
        rest_avg = d[d[pop_col] < cut]["vote_average"].mean()
        best = d.loc[d[pop_col].idxmax()]
        label = pop_col.replace("_", " ")
        st.markdown(
            "**Insights**\n"
            f"- There is a {strength} {direction} relationship between {label} and rating "
            f"(Spearman correlation = {r:.2f}).\n"
            f"- The top 10% most {label} titles average {top_avg:.2f}, compared with {rest_avg:.2f} for the rest.\n"
            f"- The title with the highest {label} is {best['title']} (rating {best['vote_average']:.1f})."
        )

    # Chart 11: Average rating by genre
    st.subheader("Average rating by genre")
    gr = (
        title_genres[title_genres["title_id"].isin(ids)]
        .merge(genres, on="genre_id")
        .merge(f[["title_id", "vote_average"]], on="title_id")
    )
    avg = (
        gr.groupby("genre_name")["vote_average"]
        .agg(avg_rating="mean", n="count")
        .reset_index()
    )
    avg = avg[avg["n"] >= 10].sort_values("avg_rating", ascending=False)
    fig = px.bar(avg, x="genre_name", y="avg_rating")
    fig.update_yaxes(range=[0, 10], title="average rating")
    fig.update_xaxes(title="genre")
    st.plotly_chart(style(fig), use_container_width=True)

    if len(avg):
        best, worst = avg.iloc[0], avg.iloc[-1]
        overall = f["vote_average"].mean()
        above = int((avg["avg_rating"] > overall).sum())
        st.markdown(
            "**Insights**\n"
            f"- {best['genre_name']} has the highest average rating ({best['avg_rating']:.2f}) "
            f"and {worst['genre_name']} has the lowest ({worst['avg_rating']:.2f}), a gap of "
            f"{best['avg_rating'] - worst['avg_rating']:.2f} points.\n"
            f"- {above} of {len(avg)} genres are rated above the overall average of {overall:.2f}.\n"
            f"- Only genres with at least 10 titles are shown, so small genres do not distort the result."
        )

with tab4:
    st.subheader("Top rated titles")
    top = (
        f[f["vote_count"] >= 50]
        .sort_values("vote_average", ascending=False)
        .head(10)[["title", "media_type", "release_year", "language", "vote_average", "vote_count"]]
    )
    st.dataframe(top, use_container_width=True, hide_index=True)
