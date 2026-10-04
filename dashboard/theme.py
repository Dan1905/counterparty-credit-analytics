"""Design tokens, the global stylesheet and the shared Plotly look.

Everything visual is defined once here: colours, the type scale (11 / 12 / 13 / 14 /
16 / 26 px), the spacing scale (4 / 8 / 12 / 16 / 24 / 32 px) and one CSS class per
reusable component in ``dashboard.components``.
"""

from __future__ import annotations

import plotly.graph_objects as go

# --------------------------------------------------------------------------- #
# Tokens
# --------------------------------------------------------------------------- #
BG = "#0d0f13"
SURFACE = "#12151a"
SURFACE_RAISED = "#171b22"
BORDER = "#232831"
BORDER_SOFT = "#1a1e25"
TEXT_PRIMARY = "#e4e7eb"
TEXT_SECONDARY = "#9aa3af"
TEXT_MUTED = "#6b7480"
GRID = "#1c2028"

ACCENT = "#4f83cc"
NEUTRAL = "#7b8492"

# Reserved status colours: always shown together with a text label.
GOOD = "#3ea76a"
WARN = "#d9a12b"
BAD = "#de5450"
STATUS_COLOURS = {"Normal": GOOD, "Warning": WARN, "Breach": BAD}
CATEGORY_COLOURS = {"Low": GOOD, "Moderate": NEUTRAL, "Elevated": WARN, "High": BAD}

# Ordered one-hue ramp for exposure measures (EE -> PFE 95 -> PFE 99), brightest = most severe.
BLUE_RAMP = ["#184f95", "#3987e5", "#86b6ef"]
# Categorical series (fixed order) - validated for colour-vision separation on BG.
SERIES = ["#4f83cc", "#20a89a", "#a078d4"]
PRODUCT_COLOURS = {
    "Equity Option": SERIES[0],
    "FX Forward": SERIES[1],
    "Interest Rate Swap": SERIES[2],
}

FONT_STACK = "Inter, 'IBM Plex Sans', -apple-system, 'Segoe UI', Roboto, sans-serif"
MILLION = 1_000_000.0
SIDEBAR_WIDTH = 224


# --------------------------------------------------------------------------- #
# Plotly
# --------------------------------------------------------------------------- #
def style_figure(fig: go.Figure, height: int = 340, money_axis: str | None = None) -> go.Figure:
    """Apply the shared chart look: transparent surface, muted grid, responsive width.

    Legends are drawn by the chart container (HTML, so they wrap instead of
    clipping); the top margin only has to hold reference-line labels.
    """
    fig.update_layout(
        height=height,
        autosize=True,
        margin=dict(l=8, r=16, t=24, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT_STACK, size=12, color=TEXT_SECONDARY),
        hoverlabel=dict(
            bgcolor=SURFACE_RAISED, bordercolor=BORDER,
            font=dict(family=FONT_STACK, size=12, color=TEXT_PRIMARY),
        ),
        bargap=0.34,
        bargroupgap=0.1,
        barcornerradius=2,
        title_text="",
    )
    fig.update_xaxes(
        showgrid=False, linecolor=BORDER, tickcolor=BORDER, automargin=True,
        tickfont=dict(color=TEXT_SECONDARY, size=11), title_font=dict(size=11, color=TEXT_MUTED),
        title_standoff=12,
    )
    fig.update_yaxes(
        gridcolor=GRID, zeroline=True, zerolinecolor=BORDER, automargin=True, nticks=6,
        tickfont=dict(color=TEXT_SECONDARY, size=11), title_font=dict(size=11, color=TEXT_MUTED),
        title_standoff=12,
    )
    if money_axis == "y":
        fig.update_yaxes(tickprefix="₹", ticksuffix="M")
    elif money_axis == "x":
        fig.update_xaxes(tickprefix="₹", ticksuffix="M", showgrid=True, gridcolor=GRID, nticks=6)
        fig.update_yaxes(showgrid=False)
    return fig


# --------------------------------------------------------------------------- #
# Stylesheet
# --------------------------------------------------------------------------- #
def active_nav_css(href: str) -> str:
    """Highlight the sidebar link of the current page (matched by its href)."""
    link = f'[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"][href="{href}"]'
    return (
        f"<style>{link} {{ background: {ACCENT}26; border-left-color: {ACCENT}; }}"
        f"{link} p {{ color: {TEXT_PRIMARY}; font-weight: 600; }}"
        f'{link} [data-testid="stIconMaterial"] {{ color: {ACCENT}; }}</style>'
    )


CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');

:root {{
  --bg: {BG}; --surface: {SURFACE}; --raised: {SURFACE_RAISED};
  --border: {BORDER}; --border-soft: {BORDER_SOFT};
  --text: {TEXT_PRIMARY}; --text-2: {TEXT_SECONDARY}; --text-3: {TEXT_MUTED};
  --accent: {ACCENT}; --good: {GOOD}; --warn: {WARN}; --bad: {BAD};
  --s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px; --s5: 24px; --s6: 32px;
  --f-meta: 11px; --f-small: 12px; --f-body: 13px; --f-strong: 14px; --f-section: 16px;
  --f-metric: 26px; --f-title: 26px;
  --radius: 3px;
}}

/* ---- App shell -------------------------------------------------------- */
html, body, .stApp, [data-testid="stSidebar"], button, input, textarea, select {{ font-family: {FONT_STACK}; }}
.stApp {{ background: var(--bg); }}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stMainBlockContainer"] {{ padding: 56px var(--s6) 48px var(--s6); max-width: 1680px; }}
footer, #MainMenu, a.anchor-link, [data-testid="stHeaderActionElements"] {{ display: none !important; }}
@media (max-width: 800px) {{ [data-testid="stMainBlockContainer"] {{ padding: 56px var(--s4) var(--s6) var(--s4); }} }}

/* ---- Sidebar ---------------------------------------------------------- */
section[data-testid="stSidebar"] {{ border-right: 1px solid var(--border); }}
section[data-testid="stSidebar"][aria-expanded="true"] {{
  width: {SIDEBAR_WIDTH}px !important; min-width: {SIDEBAR_WIDTH}px !important; max-width: {SIDEBAR_WIDTH}px !important;
}}
[data-testid="stSidebarHeader"] {{ height: 40px; min-height: 40px; padding: var(--s2) var(--s3); }}
[data-testid="stSidebarContent"] {{ padding: 0; }}
[data-testid="stSidebarUserContent"] {{ padding: 0 var(--s3) var(--s5) var(--s3); }}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{ gap: var(--s1); }}

.brand {{ padding: 0 var(--s3) var(--s4) var(--s3); margin-bottom: var(--s2); border-bottom: 1px solid var(--border); }}
.brand .b1 {{ font-size: var(--f-small); font-weight: 600; letter-spacing: 0.12em; line-height: 1.5; color: var(--text); }}
.brand .b2 {{ font-size: var(--f-meta); color: var(--text-3); margin-top: var(--s1); }}

/* Navigation item (st.page_link): the whole row is the link. */
[data-testid="stSidebar"] [data-testid="stPageLink"] {{ width: 100%; }}
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] {{
  display: flex; align-items: center; gap: var(--s3); width: 100%; height: 34px; box-sizing: border-box;
  padding: 0 var(--s3); border-radius: 2px; border-left: 2px solid transparent;
  background: transparent; text-decoration: none; transition: none;
}}
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] p {{
  font-size: var(--f-body); font-weight: 500; color: var(--text-2); line-height: 1; margin: 0;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}}
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] [data-testid="stIconMaterial"] {{
  font-size: 18px; width: 18px; flex: none; color: var(--text-3);
}}
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"]:hover {{ background: var(--surface); }}
[data-testid="stSidebar"] [data-testid="stPageLink-NavLink"]:hover p {{ color: var(--text); }}
.side-label {{
  font-size: var(--f-meta); letter-spacing: 0.1em; text-transform: uppercase; color: var(--text-3);
  padding: var(--s4) var(--s3) var(--s1) var(--s3); margin-top: var(--s3); border-top: 1px solid var(--border);
}}
[data-testid="stSidebar"] .stSelectbox, [data-testid="stSidebar"] .stButton {{ padding: var(--s1) var(--s1); }}
[data-testid="stSidebar"] .stButton button {{ min-height: 34px; font-size: var(--f-body); }}
.sys {{ padding: var(--s1) var(--s3) 0 var(--s3); font-size: var(--f-small); color: var(--text-2); }}
.sys div {{ display: flex; justify-content: space-between; gap: var(--s2); padding: var(--s1) 0; line-height: 1.4; }}
.sys .k {{ color: var(--text-3); flex: none; }}
.sys .v {{ text-align: right; overflow-wrap: anywhere; }}
.sys .ok {{ justify-content: flex-start; align-items: center; color: var(--text); }}
.sys .dot {{ width: 6px; height: 6px; border-radius: 50%; background: var(--good); flex: none; }}

/* ---- Page header ------------------------------------------------------ */
.ph {{ display: flex; justify-content: space-between; align-items: flex-end; gap: var(--s2) var(--s5); flex-wrap: wrap;
       padding-bottom: var(--s4); border-bottom: 1px solid var(--border); }}
.ph .tt {{ min-width: 0; }}
.ph h1 {{ font-size: var(--f-title); font-weight: 600; line-height: 1.2; letter-spacing: -0.01em; margin: 0; padding: 0;
          color: var(--text); overflow-wrap: anywhere; }}
.ph .d {{ font-size: var(--f-body); color: var(--text-2); margin-top: var(--s1); line-height: 1.5; }}
.ph .m {{ font-size: var(--f-small); color: var(--text-3); line-height: 1.5; font-variant-numeric: tabular-nums; }}
.ph .m b {{ color: var(--text-2); font-weight: 500; }}
.ph .m span {{ white-space: nowrap; }}

/* ---- Section header, chart container, notes -------------------------- */
.sh {{ margin-top: var(--s4); }}
.sh .t {{ font-size: var(--f-section); font-weight: 600; line-height: 1.4; color: var(--text); }}
.sh .s {{ font-size: var(--f-small); color: var(--text-3); margin-top: var(--s1); line-height: 1.5; }}
.ch .t {{ font-size: var(--f-strong); font-weight: 600; line-height: 1.4; color: var(--text); }}
.ch .s {{ font-size: var(--f-small); color: var(--text-3); margin-top: var(--s1); line-height: 1.5; }}
.ch .lg {{ display: flex; flex-wrap: wrap; gap: var(--s1) var(--s4); margin-top: var(--s3); }}
.ch .lg span {{ display: inline-flex; align-items: center; gap: var(--s2); font-size: var(--f-small); color: var(--text-2); white-space: nowrap; }}
.ch .lg i {{ width: 10px; height: 10px; border-radius: 2px; flex: none; }}
.ch .lg i.ln {{ height: 2px; width: 16px; border-radius: 0; }}
.note {{ font-size: var(--f-small); color: var(--text-3); line-height: 1.6; overflow-wrap: anywhere; }}
.note a {{ color: var(--text-2); text-decoration: none; }}
.note a:hover {{ color: var(--text); }}

/* ---- KPI cards -------------------------------------------------------- */
.kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(176px, 1fr)); gap: 1px;
         background: var(--border); border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; }}
.kpi {{ display: flex; flex-direction: column; min-width: 0; min-height: 132px; box-sizing: border-box;
        padding: var(--s4); background: var(--surface); }}
.kpi .l {{ display: flex; align-items: flex-start; gap: var(--s2); font-size: var(--f-meta); font-weight: 500;
           letter-spacing: 0.07em; text-transform: uppercase; color: var(--text-3); line-height: 1.4; min-height: 16px; }}
.kpi .l svg {{ width: 14px; height: 14px; flex: none; stroke: var(--text-3); margin-top: 1px; }}
.kpi .l span {{ min-width: 0; overflow-wrap: anywhere; }}
.kpi .v {{ font-size: var(--f-metric); font-weight: 600; color: var(--text); margin-top: var(--s2); line-height: 1.2;
           font-variant-numeric: tabular-nums; letter-spacing: -0.01em; overflow-wrap: anywhere; }}
.kpi .x {{ font-size: var(--f-small); color: var(--text); font-weight: 500; margin-top: var(--s2); line-height: 1.4;
           font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }}
.kpi .y {{ font-size: var(--f-small); color: var(--text-3); margin-top: 2px; line-height: 1.4;
           font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }}
.kpi.bad {{ box-shadow: inset 0 2px 0 var(--bad); }}   .kpi.bad .v {{ color: var(--bad); }}
.kpi.warn {{ box-shadow: inset 0 2px 0 var(--warn); }} .kpi.warn .v {{ color: var(--warn); }}
.kpi.good .v {{ color: var(--good); }}

/* ---- Status badge ----------------------------------------------------- */
.bdg {{ display: inline-block; font-size: var(--f-meta); font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase;
        padding: 2px var(--s2); border-radius: 2px; border: 1px solid; line-height: 1.5; white-space: nowrap; }}
.bdg.good {{ color: var(--good); border-color: {GOOD}55; background: {GOOD}14; }}
.bdg.warn {{ color: var(--warn); border-color: {WARN}55; background: {WARN}14; }}
.bdg.bad  {{ color: var(--bad);  border-color: {BAD}66;  background: {BAD}1a; }}
.bdg.neutral {{ color: var(--text-2); border-color: var(--border); background: var(--raised); }}
.bdg.lg {{ font-size: var(--f-small); padding: var(--s1) var(--s3); }}

/* ---- Risk table ------------------------------------------------------- */
.tw {{ overflow-x: auto; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); }}
table.rt {{ width: 100%; border-collapse: collapse; font-size: var(--f-body); font-variant-numeric: tabular-nums; margin: 0; }}
table.rt th {{ font-size: var(--f-meta); font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-3);
               padding: var(--s2) var(--s3); border: 0; border-bottom: 1px solid var(--border); background: var(--raised);
               white-space: nowrap; text-align: left; vertical-align: bottom; line-height: 1.4; }}
table.rt td {{ padding: var(--s2) var(--s3); border: 0; border-bottom: 1px solid var(--border-soft); color: var(--text);
               white-space: nowrap; vertical-align: middle; line-height: 1.5; height: 40px; box-sizing: border-box; }}
table.rt tbody tr:last-child td {{ border-bottom: 0; }}
table.rt tbody tr:hover td {{ background: var(--raised); }}
table.rt .r {{ text-align: right; }}
table.rt .c {{ text-align: center; }}
table.rt td.w {{ white-space: normal; min-width: 180px; max-width: 320px; overflow-wrap: anywhere; }}
table.rt .ent {{ display: block; white-space: normal; min-width: 150px; max-width: 260px; overflow-wrap: anywhere; }}
table.rt .ent small {{ display: block; font-size: var(--f-small); color: var(--text-3); line-height: 1.4; }}
table.rt .dim {{ color: var(--text-2); }}
table.rt a {{ color: var(--accent); text-decoration: none; font-weight: 600; }}
table.rt a:hover {{ text-decoration: underline; }}
table.rt tfoot td {{ border-top: 1px solid var(--border); border-bottom: 0; color: var(--text-2); font-weight: 600; background: var(--raised); }}
.tg {{ color: var(--good); }} .ta {{ color: var(--warn); }} .tb {{ color: var(--bad); }}
.ubar {{ display: inline-block; vertical-align: middle; width: 56px; height: 4px; background: var(--border);
         margin-right: var(--s2); position: relative; }}
.ubar i {{ position: absolute; left: 0; top: 0; bottom: 0; }}

/* ---- Metric rows ------------------------------------------------------ */
.mr {{ border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); padding: var(--s1) var(--s4); }}
.mr .row {{ display: flex; justify-content: space-between; align-items: baseline; gap: var(--s4); padding: var(--s2) 0;
            border-bottom: 1px solid var(--border-soft); font-size: var(--f-body); line-height: 1.5; }}
.mr .row:last-child {{ border-bottom: 0; }}
.mr .k {{ color: var(--text-2); min-width: 0; overflow-wrap: anywhere; }}
.mr .v {{ color: var(--text); font-weight: 500; font-variant-numeric: tabular-nums; text-align: right; flex: none; max-width: 65%; }}
.mr .row.total {{ border-top: 1px solid var(--border); }}
.mr .row.total .k, .mr .row.total .v {{ font-weight: 600; color: var(--text); }}
.mr a, .rep a, .bn a {{ color: var(--accent); text-decoration: none; font-weight: 600; }}
.mr a:hover, .rep a:hover, .bn a:hover {{ text-decoration: underline; }}
.mr .dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: var(--s2); }}
.mr .cnt {{ display: inline-block; min-width: 20px; font-weight: 600; color: var(--text); }}

/* ---- Warning / breach banner, empty state ---------------------------- */
.bn {{ display: grid; grid-template-columns: 80px minmax(0, 1fr) auto; gap: var(--s1) var(--s4); align-items: center;
       padding: var(--s3) var(--s4); border: 1px solid var(--border); border-left: 3px solid var(--text-3);
       border-radius: 2px; background: var(--surface); margin-bottom: var(--s2); }}
.bn:last-child {{ margin-bottom: 0; }}
.bn.bad {{ border-left-color: var(--bad); }} .bn.warn {{ border-left-color: var(--warn); }} .bn.good {{ border-left-color: var(--good); }}
.bn .sev {{ font-size: var(--f-meta); font-weight: 600; letter-spacing: 0.1em; color: var(--text-3); }}
.bn.bad .sev {{ color: var(--bad); }} .bn.warn .sev {{ color: var(--warn); }} .bn.good .sev {{ color: var(--good); }}
.bn .body {{ min-width: 0; font-size: var(--f-body); line-height: 1.5; color: var(--text-2); overflow-wrap: anywhere; }}
.bn .body .who {{ color: var(--text); font-weight: 600; }}
.bn .body .who small {{ font-size: var(--f-small); font-weight: 400; color: var(--text-3); margin-left: var(--s2); }}
.bn .fig {{ font-size: var(--f-section); font-weight: 600; color: var(--text); font-variant-numeric: tabular-nums;
            text-align: right; line-height: 1.3; white-space: nowrap; }}
.bn .fig small {{ display: block; font-size: var(--f-meta); font-weight: 400; color: var(--text-3); }}
@media (max-width: 640px) {{ .bn {{ grid-template-columns: minmax(0, 1fr) auto; }} .bn .sev {{ grid-column: 1 / -1; }} }}
.empty {{ border: 1px dashed var(--border); border-radius: var(--radius); padding: var(--s5) var(--s4); text-align: center;
          font-size: var(--f-body); color: var(--text-3); line-height: 1.5; }}
.empty b {{ display: block; color: var(--text-2); font-weight: 600; margin-bottom: var(--s1); }}

/* ---- Counterparty header --------------------------------------------- */
.cph {{ display: flex; justify-content: space-between; align-items: flex-start; gap: var(--s4); flex-wrap: wrap;
        padding: var(--s4); border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); }}
.cph .who {{ min-width: 0; flex: 1 1 320px; }}
.cph .id {{ font-size: var(--f-small); font-weight: 600; letter-spacing: 0.1em; color: var(--accent); }}
.cph .nm {{ font-size: 20px; font-weight: 600; line-height: 1.3; color: var(--text); margin-top: var(--s1); overflow-wrap: anywhere; }}
.cph .meta {{ display: flex; gap: var(--s2) var(--s5); margin-top: var(--s3); font-size: var(--f-small); color: var(--text-3); flex-wrap: wrap; }}
.cph .meta b {{ color: var(--text); font-weight: 500; margin-left: var(--s2); }}
.cph .st {{ font-size: var(--f-meta); color: var(--text-3); letter-spacing: 0.08em; text-transform: uppercase; }}
.cph .st .bdg {{ margin-top: var(--s2); }}

/* ---- Limit utilisation ----------------------------------------------- */
.lim {{ border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); padding: var(--s4); }}
.lim .top {{ display: flex; gap: var(--s4) var(--s6); align-items: flex-end; flex-wrap: wrap; }}
.lim .blk .k {{ font-size: var(--f-meta); letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-3); }}
.lim .blk .v {{ font-size: var(--f-metric); font-weight: 600; line-height: 1.2; color: var(--text); margin-top: var(--s1);
                font-variant-numeric: tabular-nums; white-space: nowrap; }}
.lim .right {{ margin-left: auto; text-align: right; }}
.lim .right .hd {{ font-size: var(--f-small); color: var(--text-2); margin-bottom: var(--s2); }}
.lim .track {{ position: relative; height: 12px; background: var(--raised); border: 1px solid var(--border); margin-top: var(--s5); }}
.lim .fill {{ position: absolute; left: 0; top: 0; bottom: 0; }}
.lim .tick {{ position: absolute; top: -4px; bottom: -4px; width: 1px; background: var(--text-3); }}
.lim .now {{ position: absolute; top: -8px; bottom: -8px; width: 2px; margin-left: -1px; background: var(--text); }}
.lim .scale {{ position: relative; height: 20px; margin-top: var(--s2); font-size: var(--f-meta); color: var(--text-3); }}
.lim .scale span {{ position: absolute; top: 0; transform: translateX(-50%); white-space: nowrap; }}
.lim .scale span:first-child {{ transform: none; }}
.lim .key {{ display: flex; flex-wrap: wrap; gap: var(--s1) var(--s4); margin-top: var(--s2); font-size: var(--f-small); color: var(--text-2); }}
.lim .key b {{ color: var(--text); font-weight: 600; }}

/* ---- Risk commentary -------------------------------------------------- */
.rep {{ border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface);
        padding: var(--s4) var(--s5) var(--s5) var(--s5); max-width: 1040px; }}
.rep h4 {{ font-size: var(--f-meta); font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; color: var(--text-3);
           margin: var(--s4) 0 var(--s2) 0 !important; padding: var(--s4) 0 0 0 !important;
           border-top: 1px solid var(--border-soft); line-height: 1.4; }}
.rep h4:first-child {{ border-top: 0; padding-top: 0 !important; margin-top: 0 !important; }}
.rep p {{ font-size: var(--f-body); line-height: 1.7; color: var(--text); margin: 0 0 var(--s2) 0; overflow-wrap: anywhere; }}
.rep p:last-child {{ margin-bottom: 0; }}
.rep ul {{ margin: 0; padding-left: var(--s4); }}
.rep li {{ font-size: var(--f-body); line-height: 1.7; color: var(--text); overflow-wrap: anywhere; }}
.rep .cpn {{ display: flex; gap: var(--s2); align-items: center; flex-wrap: wrap; margin: var(--s4) 0 var(--s1) 0;
             font-size: var(--f-body); font-weight: 600; color: var(--text); }}
.rep .cpn small {{ font-size: var(--f-small); font-weight: 400; color: var(--text-3); }}

/* ---- Streamlit widgets ------------------------------------------------ */
[data-testid="stWidgetLabel"] p {{ font-size: var(--f-meta) !important; letter-spacing: 0.07em; text-transform: uppercase; color: var(--text-3); }}
.stSelectbox div[data-baseweb="select"] > div, .stMultiSelect div[data-baseweb="select"] > div {{
  background: var(--surface); border-color: var(--border); font-size: var(--f-body); }}
.stButton button, .stDownloadButton button {{ font-size: var(--f-body); font-weight: 500; border-radius: var(--radius); }}
.stButton button p, .stDownloadButton button p {{ font-size: var(--f-body); white-space: nowrap; }}
.stMain .stButton button, .stMain .stDownloadButton button, [data-testid="stSidebar"] .stButton button {{
  border-color: var(--border); background: var(--surface); }}
.stMain .stButton button:hover, .stMain .stDownloadButton button:hover, [data-testid="stSidebar"] .stButton button:hover {{
  border-color: var(--accent); color: var(--text); }}
.stMain .stButton button[kind="primary"] {{ background: var(--accent); border-color: var(--accent); color: #fff; }}
[data-testid="stExpander"] details {{ border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); }}
[data-testid="stExpander"] summary p {{ font-size: var(--f-body); font-weight: 500; }}
[data-testid="stDataFrame"] {{ border: 1px solid var(--border); border-radius: var(--radius); }}
[data-testid="stPlotlyChart"] {{ width: 100%; overflow: hidden; }}
</style>
"""
