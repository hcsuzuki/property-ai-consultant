import math
import os
from collections import Counter

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="AI不動産投資コンサルタント",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────────────────────────────────────
# CSS
# ──────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.main-header {
    text-align: center;
    padding: 2.5rem 2rem;
    background: linear-gradient(135deg, #1a237e 0%, #283593 60%, #3949ab 100%);
    color: white;
    border-radius: 16px;
    margin-bottom: 2rem;
    box-shadow: 0 8px 32px rgba(26,35,126,.3);
}
.main-header h1 { font-size: 2.2rem; font-weight: 700; margin-bottom: .4rem; }
.main-header p  { font-size: .95rem; opacity: .9; margin: 0; }

.section-title {
    font-size: 1.15rem; font-weight: 700; color: #1a237e;
    border-left: 4px solid #3949ab; padding-left: .9rem;
    margin: 2rem 0 1rem;
}

.card {
    background: white;
    border-radius: 12px;
    padding: 1.4rem 1.6rem;
    box-shadow: 0 2px 12px rgba(0,0,0,.08);
    margin-bottom: 1rem;
    height: 100%;
    word-wrap: break-word; overflow-wrap: break-word; overflow: hidden;
}
.card h4 { color: #1a237e; border-bottom: 2px solid #e8eaf6; padding-bottom: .5rem; margin-bottom: 1rem; }

.row { display:flex; justify-content:space-between; padding:.35rem 0; border-bottom:1px solid #f5f5f5; }
.row:last-child { border-bottom: none; }
.row-label { color: #666; font-size: .88rem; }
.row-value { font-weight: 600; color: #1a237e; font-size: .92rem; }

.rec-card {
    padding: 1.4rem 1.8rem; border-radius: 12px;
    border-left: 6px solid; margin-bottom: 1.5rem;
    background: white; box-shadow: 0 2px 12px rgba(0,0,0,.08);
    word-wrap: break-word; overflow-wrap: break-word; overflow: hidden;
}
.rec-hold  { border-color: #43a047; }
.rec-sell  { border-color: #fb8c00; }
.rec-check { border-color: #1e88e5; }

.tag-good { background:#e8f5e9; color:#2e7d32; padding:.4rem .7rem; border-radius:8px; margin-bottom:.45rem; font-size:.88rem; display:block; }
.tag-risk { background:#fff3e0; color:#e65100; padding:.4rem .7rem; border-radius:8px; margin-bottom:.45rem; font-size:.88rem; display:block; }

.disclaimer {
    font-size:.75rem; color:#999; padding:1rem;
    background:#fafafa; border:1px solid #eee;
    border-radius:8px; margin-top:3rem; line-height:1.7;
}

div[data-testid="stExpander"] { border:1px solid #e8eaf6; border-radius:10px; margin-bottom:.5rem; }
</style>
""", unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def usd(amount: float) -> str:
    if amount >= 1_000_000:
        return f"${amount/1_000_000:.2f}M"
    return f"${amount:,.0f}"


def jpy(amount_usd: float, rate: float) -> str:
    v = amount_usd * rate
    if v >= 100_000_000:
        return f"約{v/100_000_000:.1f}億円"
    if v >= 10_000:
        return f"約{v/10_000:.0f}万円"
    return f"約{v:,.0f}円"


def calc_financials(
    purchase_price: float,
    down_pct: float,
    closing_pct: float,
    monthly_rent: float,
    expense_ratio: float,
    rate: float,
    term_years: int,
    hoa: float,
    is_cash: bool = False,
) -> dict:
    closing = purchase_price * (closing_pct / 100)

    if is_cash:
        down         = purchase_price
        loan         = 0.0
        mortgage     = 0.0
        cash_needed  = purchase_price + closing
        eff_down_pct = 100.0
    else:
        down         = purchase_price * (down_pct / 100)
        loan         = purchase_price - down
        cash_needed  = down + closing
        eff_down_pct = down_pct
        mr = (rate / 100) / 12
        n  = term_years * 12
        if mr > 0:
            mortgage = loan * (mr * (1 + mr) ** n) / ((1 + mr) ** n - 1)
        else:
            mortgage = loan / n if n > 0 else 0

    monthly_expenses = monthly_rent * (expense_ratio / 100)
    monthly_noi  = monthly_rent - monthly_expenses - hoa
    annual_noi   = monthly_noi * 12
    cap_rate     = (annual_noi / purchase_price * 100) if purchase_price else 0
    monthly_cf   = monthly_noi - mortgage
    annual_cf    = monthly_cf * 12
    coc          = (annual_cf / cash_needed * 100) if cash_needed else 0
    grm          = purchase_price / (monthly_rent * 12) if monthly_rent else 0
    r2p          = (monthly_rent / purchase_price * 100) if purchase_price else 0

    return dict(
        is_cash=is_cash,
        purchase_price=purchase_price, down_payment=down, down_payment_pct=eff_down_pct,
        closing_costs=closing, loan_amount=loan, total_cash_needed=cash_needed,
        monthly_mortgage=mortgage, monthly_gross_income=monthly_rent,
        monthly_expenses=monthly_expenses, monthly_hoa=hoa, monthly_noi=monthly_noi,
        annual_noi=annual_noi, cap_rate=cap_rate, monthly_cash_flow=monthly_cf,
        annual_cash_flow=annual_cf, coc_return=coc, grm=grm, rent_to_price=r2p,
        mortgage_rate=rate if not is_cash else 0,
        loan_term_years=term_years if not is_cash else 0,
        expense_ratio=expense_ratio,
    )


# ──────────────────────────────────────────────────────────────────────────────
# 基本計算関数
# ──────────────────────────────────────────────────────────────────────────────

def calc_remaining_loan_balance(loan: float, rate_pct: float, term_years: int, year: int) -> float:
    mr = (rate_pct / 100) / 12
    n  = term_years * 12
    k  = year * 12
    if loan <= 0 or n <= 0: return 0.0
    if mr <= 0: return max(0.0, loan * (1 - k / n))
    if k >= n:  return 0.0
    return loan * ((1 + mr)**n - (1 + mr)**k) / ((1 + mr)**n - 1)


def calc_10year_simulation(fin: dict, rent_growth: float = 3.0, appreciation: float = 3.0) -> list:
    base_rent  = fin["monthly_gross_income"]
    base_value = fin["purchase_price"]
    is_cash    = fin.get("is_cash", False)
    mortgage   = fin["monthly_mortgage"]
    exp_ratio  = fin["expense_ratio"]
    hoa        = fin["monthly_hoa"]
    initial    = fin["total_cash_needed"]
    cumulative_cf = 0.0
    results = []
    for yr in range(1, 11):
        rm_y  = base_rent  * (1 + rent_growth  / 100) ** yr
        val_y = base_value * (1 + appreciation  / 100) ** yr
        noi_y = rm_y * (1 - exp_ratio / 100) - hoa
        cf_y  = (noi_y - mortgage) * 12
        cumulative_cf += cf_y
        loan_bal_y = (0.0 if is_cash else
                      calc_remaining_loan_balance(fin["loan_amount"], fin["mortgage_rate"],
                                                  fin["loan_term_years"], yr))
        equity_y = val_y - loan_bal_y
        results.append({
            "年":         f"{yr}年目",
            "物件価値":   int(val_y),
            "月額賃料":   int(rm_y),
            "年間NOI":    int(noi_y * 12),
            "年間CF":     int(cf_y),
            "累積CF":     int(cumulative_cf),
            "ローン残高": int(loan_bal_y),
            "エクイティ": int(equity_y),
            "総リターン": int(equity_y - initial + cumulative_cf),
        })
    return results


def calc_depreciation(purchase_price: float, land_pct: float = 20.0) -> dict:
    land_val    = purchase_price * land_pct / 100
    depr_basis  = purchase_price - land_val
    annual_depr = depr_basis / 27.5
    return {
        "land_value":           land_val,
        "land_pct":             land_pct,
        "depreciable_basis":    depr_basis,
        "annual_depreciation":  annual_depr,
        "monthly_depreciation": annual_depr / 12,
        "tax_savings":          {r: annual_depr * r / 100 for r in [20, 25, 30, 37]},
    }


def calc_breakeven_rent(fin: dict) -> dict:
    mortgage  = fin["monthly_mortgage"]
    hoa       = fin["monthly_hoa"]
    net_ratio = 1 - fin["expense_ratio"] / 100
    if net_ratio <= 0:
        return {"error": "経費率≥100%"}
    be_rent = (hoa + mortgage) / net_ratio
    curr    = fin["monthly_gross_income"]
    margin  = curr - be_rent
    return {
        "breakeven_rent":     be_rent,
        "current_rent":       curr,
        "margin":             margin,
        "margin_pct":         (margin / be_rent * 100) if be_rent > 0 else 0,
        "is_above_breakeven": margin >= 0,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Phase 2: 高度財務指標 計算関数
# ──────────────────────────────────────────────────────────────────────────────

def calc_irr(fin: dict, sim: list, exit_sell_pct: float = 6.0) -> dict:
    """IRR（内部収益率）とEquity Multipleを計算"""
    try:
        import numpy_financial as npf
    except ImportError:
        return {"error": "numpy-financial が必要です（pip install numpy-financial）"}
    initial    = -fin["total_cash_needed"]
    annual_cfs = [row["年間CF"] for row in sim]
    last_row   = sim[-1]
    sell_price = last_row["物件価値"]
    loan_bal   = last_row["ローン残高"]
    exit_equity = sell_price - loan_bal - sell_price * exit_sell_pct / 100
    cf = [initial] + annual_cfs[:]
    cf[-1] += exit_equity
    try:
        irr_val = npf.irr(cf)
        total_in = sum(annual_cfs) + exit_equity
        em = total_in / abs(initial) if initial != 0 else 0
        return {
            "irr":               irr_val * 100,
            "equity_multiple":   em,
            "exit_equity":       exit_equity,
            "total_cash_received": total_in,
            "initial_investment": abs(initial),
        }
    except Exception as e:
        return {"error": f"IRR計算失敗: {str(e)}"}


def calc_dscr(fin: dict) -> dict:
    """DSCR（元利返済カバー率）を計算"""
    if fin.get("is_cash"):
        return {"dscr": float("inf"), "is_cash": True, "pass": True, "label": "N/A（全キャッシュ）"}
    annual_noi  = fin["annual_noi"]
    annual_debt = fin["monthly_mortgage"] * 12
    if annual_debt <= 0:
        return {"error": "ローン返済額が0です"}
    dscr = annual_noi / annual_debt
    return {
        "dscr":               dscr,
        "annual_noi":         annual_noi,
        "annual_debt_service": annual_debt,
        "pass":               dscr >= 1.25,
        "label": "優秀" if dscr >= 1.5 else "合格" if dscr >= 1.25 else "警告" if dscr >= 1.0 else "危険",
    }


def calc_1pct_rule(fin: dict) -> dict:
    """1%ルール判定（月額賃料 ÷ 購入価格）"""
    monthly_rent = fin["monthly_gross_income"]
    purchase     = fin["purchase_price"]
    target       = purchase * 0.01
    ratio        = monthly_rent / purchase * 100
    return {
        "ratio":        ratio,
        "target_rent":  target,
        "current_rent": monthly_rent,
        "pass":         ratio >= 1.0,
        "gap":          monthly_rent - target,
    }


def calc_breakeven_occupancy(fin: dict) -> dict:
    """損益分岐点稼働率（Break-even Occupancy）を計算"""
    gross_rent = fin["monthly_gross_income"]
    if gross_rent <= 0:
        return {"error": "賃料が0です"}
    monthly_fixed = fin["monthly_expenses"] + fin["monthly_hoa"] + fin["monthly_mortgage"]
    be_occ = monthly_fixed / gross_rent * 100
    return {
        "breakeven_occupancy_pct": be_occ,
        "monthly_fixed_costs":     monthly_fixed,
        "gross_rent":              gross_rent,
        "safe_vacancy_pct":        100 - be_occ,
        "pass":                    be_occ < 85,
        "label": "安全" if be_occ < 75 else "普通" if be_occ < 85 else "注意" if be_occ < 95 else "危険",
    }


def calc_after_tax_cf(fin: dict, depr: dict, tax_bracket: float = 25.0) -> dict:
    """税引後キャッシュフローを計算（概算）"""
    is_cash       = fin.get("is_cash", False)
    annual_noi    = fin["annual_noi"]
    annual_depr   = depr["annual_depreciation"]
    annual_interest = fin["monthly_mortgage"] * 12 * 0.75 if not is_cash else 0
    taxable_income  = annual_noi - annual_interest - annual_depr
    if taxable_income > 0:
        tax_owed   = taxable_income * tax_bracket / 100
        tax_benefit = 0.0
    else:
        tax_owed    = 0.0
        tax_benefit = min(abs(taxable_income), 25000) * tax_bracket / 100
    after_tax_annual = fin["annual_cash_flow"] - tax_owed + tax_benefit
    return {
        "pre_tax_annual_cf":  fin["annual_cash_flow"],
        "taxable_income":     taxable_income,
        "tax_bracket_pct":    tax_bracket,
        "tax_owed":           tax_owed,
        "tax_benefit":        tax_benefit,
        "after_tax_annual_cf": after_tax_annual,
        "after_tax_monthly_cf": after_tax_annual / 12,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Charts
# ──────────────────────────────────────────────────────────────────────────────

def gauge_chart(score: int) -> go.Figure:
    color = "#00897b" if score >= 80 else "#43a047" if score >= 65 else "#fb8c00" if score >= 50 else "#e53935"
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        number={"font": {"size": 52, "color": color}, "suffix": "/100"},
        title={"text": "投資スコア", "font": {"size": 16, "color": "#1a237e"}},
        gauge={
            "axis": {"range": [0, 100], "tickvals": [0, 25, 50, 65, 80, 100]},
            "bar": {"color": color, "thickness": 0.28},
            "steps": [
                {"range": [0, 50],   "color": "#ffebee"},
                {"range": [50, 65],  "color": "#fff3e0"},
                {"range": [65, 80],  "color": "#e8f5e9"},
                {"range": [80, 100], "color": "#e0f2f1"},
            ],
            "threshold": {"line": {"color": color, "width": 4}, "thickness": 0.85, "value": score},
        },
    ))
    fig.update_layout(height=280, margin=dict(l=20, r=20, t=40, b=0),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig


def breakdown_chart(breakdown: dict) -> go.Figure:
    cats = ["立地・環境\n(30点)", "財務指標\n(40点)", "物件状態\n(20点)", "市場動向\n(10点)"]
    vals = [
        breakdown.get("location_score", 0),
        breakdown.get("financial_score", 0),
        breakdown.get("property_score", 0),
        breakdown.get("market_score", 0),
    ]
    maxs = [
        breakdown.get("location_max", 30),
        breakdown.get("financial_max", 40),
        breakdown.get("property_max", 20),
        breakdown.get("market_max", 10),
    ]
    pcts   = [v / m * 100 if m else 0 for v, m in zip(vals, maxs)]
    colors = ["#43a047" if p >= 70 else "#fb8c00" if p >= 45 else "#e53935" for p in pcts]

    fig = go.Figure()
    fig.add_trace(go.Bar(x=cats, y=maxs, marker_color="#e8eaf6", showlegend=False, name="最大"))
    fig.add_trace(go.Bar(
        x=cats, y=vals, marker_color=colors, showlegend=False,
        text=[f"{v}/{m}" for v, m in zip(vals, maxs)], textposition="outside", name="取得",
    ))
    fig.update_layout(
        barmode="overlay", height=270,
        margin=dict(l=10, r=10, t=20, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        yaxis={"showgrid": True, "gridcolor": "#f5f5f5"},
        xaxis={"showgrid": False},
        font={"size": 11},
    )
    return fig


def ten_year_chart(sim: list) -> go.Figure:
    years    = [d["年"]         for d in sim]
    values   = [d["物件価値"]   for d in sim]
    equities = [d["エクイティ"] for d in sim]
    cum_cfs  = [d["累積CF"]     for d in sim]
    colors   = ["#a5d6a7" if v >= 0 else "#ef9a9a" for v in cum_cfs]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=years, y=values,   name="物件価値",
                             line=dict(color="#1565c0", width=2), mode="lines+markers", marker=dict(size=8)))
    fig.add_trace(go.Scatter(x=years, y=equities, name="エクイティ",
                             line=dict(color="#2e7d32", width=2), mode="lines+markers", marker=dict(size=8)))
    fig.add_trace(go.Bar(x=years, y=cum_cfs, name="累積CF", marker_color=colors,
                         text=[f"${v:,.0f}" for v in cum_cfs], textposition="outside", yaxis="y2"))
    fig.update_layout(
        title="10年間 資産価値・エクイティ・累積CF推移", height=400,
        margin=dict(l=10, r=70, t=55, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        yaxis =dict(title="金額 ($)", showgrid=True, gridcolor="#f5f5f5"),
        yaxis2=dict(title="累積CF ($)", overlaying="y", side="right"),
        legend=dict(orientation="h", y=-0.18),
        xaxis =dict(showgrid=False),
    )
    return fig


def sensitivity_chart_rental(fin: dict) -> go.Figure:
    base_rent = fin["monthly_gross_income"]
    base_mort = fin["monthly_mortgage"]
    exp_ratio = fin["expense_ratio"]
    hoa       = fin["monthly_hoa"]
    is_cash   = fin.get("is_cash", False)

    rent_mults  = [-0.20, -0.10, 0.0, +0.10, +0.20, +0.30]
    price_mults = [-0.15, -0.10, -0.05, 0.0, +0.05, +0.10, +0.15]
    rent_labels  = [f"賃料{'+' if m>0 else ''}{m*100:.0f}%\n(${base_rent*(1+m):,.0f})" for m in rent_mults]
    price_labels = [f"価格{m*100:+.0f}%" for m in price_mults]

    z, text_z = [], []
    for rm in rent_mults:
        row, trow = [], []
        for pm in price_mults:
            rent_s = base_rent * (1 + rm)
            mort_s = 0.0 if is_cash else base_mort * (1 + pm)
            cf_s   = rent_s * (1 - exp_ratio / 100) - hoa - mort_s
            row.append(round(cf_s))
            trow.append(f"${cf_s:,.0f}/月")
        z.append(row)
        text_z.append(trow)

    fig = go.Figure(go.Heatmap(
        z=z, x=price_labels, y=rent_labels,
        text=text_z, texttemplate="%{text}",
        colorscale=[[0.0,"#7f0000"],[0.35,"#ef9a9a"],[0.5,"#fff9c4"],[0.65,"#a5d6a7"],[1.0,"#1b5e20"]],
        zmid=0, colorbar={"title": "月次CF ($)"},
        hovertemplate="<b>%{y} × %{x}</b><br>月次CF: %{text}<extra></extra>",
    ))
    fig.update_layout(
        title="感度分析: 賃料 × 購入価格の月次キャッシュフロー", height=360,
        margin=dict(l=10, r=80, t=55, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(title="購入価格の変動"),
        yaxis=dict(title="月額賃料の変動"),
        font={"size": 10},
    )
    return fig


def mortgage_rate_chart(market_data: dict) -> go.Figure | None:
    """FRED住宅ローン金利推移チャート"""
    rates_data = market_data.get("mortgage_rates", {})
    if rates_data.get("error"):
        return None
    fig    = go.Figure()
    colors = {"MORTGAGE30US": "#1565c0", "MORTGAGE15US": "#2e7d32"}
    for series_id, info in rates_data.items():
        if isinstance(info, dict) and "history" in info:
            dates  = [h[0] for h in info["history"]]
            values = [h[1] for h in info["history"]]
            fig.add_trace(go.Scatter(
                x=dates, y=values,
                name=f"{info['label']} ({values[-1]:.2f}%)",
                line=dict(color=colors.get(series_id, "#666"), width=2),
                mode="lines",
            ))
    fig.update_layout(
        title="住宅ローン金利推移（直近1年）", height=280,
        margin=dict(l=10, r=10, t=50, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(title="金利 (%)", ticksuffix="%"),
        xaxis=dict(showgrid=False),
        legend=dict(orientation="h", y=-0.25),
        font=dict(size=10),
    )
    return fig


# ──────────────────────────────────────────────────────────────────────────────
# Results display
# ──────────────────────────────────────────────────────────────────────────────

def show_results(
    analysis: dict,
    prop: dict,
    loc: dict,
    fin: dict,
    rate: float,
    rent_growth: float = 3.0,
    appreciation: float = 3.0,
    land_pct: float = 20.0,
    tax_bracket: float = 25.0,
    exit_cost_pct: float = 6.0,
    market_data: dict = None,
    industry_news: dict = None,
):
    score     = analysis.get("investment_score", 0)
    breakdown = analysis.get("score_breakdown", {})
    is_cash   = fin.get("is_cash", False)
    depr      = calc_depreciation(fin["purchase_price"], land_pct)
    sim       = calc_10year_simulation(fin, rent_growth, appreciation)

    # ── Score section ─────────────────────────────────────────────────────────
    st.markdown('<div class="section-title">📊 投資スコア分析</div>', unsafe_allow_html=True)
    c1, c2 = st.columns([1, 1.4])
    with c1:
        st.plotly_chart(gauge_chart(score), use_container_width=True)
        if   score >= 80: label, color = "優秀 ― 強く推奨",  "#00897b"
        elif score >= 65: label, color = "良好 ― 推奨",      "#43a047"
        elif score >= 50: label, color = "普通 ― 要検討",    "#fb8c00"
        else:             label, color = "要注意 ― 慎重に",  "#e53935"
        st.markdown(
            f"<div style='text-align:center;font-size:1.1rem;font-weight:700;"
            f"color:{color};margin-top:-.5rem'>{label}</div>",
            unsafe_allow_html=True,
        )
    with c2:
        st.plotly_chart(breakdown_chart(breakdown), use_container_width=True)

    # ── Recommendation ────────────────────────────────────────────────────────
    rec        = analysis.get("recommendation", "")
    hold_years = analysis.get("hold_years", "")
    if "長期" in rec or "保有" in rec:
        rec_class, icon = "rec-hold",  "🏠 長期保有推奨"
    elif "売却" in rec or "短期" in rec:
        rec_class, icon = "rec-sell",  "💰 早期売却推奨"
    else:
        rec_class, icon = "rec-check", "🔍 条件付き推奨"

    period = (f"<div style='font-size:.9rem;color:#666;margin-top:.3rem'>推奨保有期間: {hold_years}</div>"
              if hold_years else "")
    st.markdown(f"""
    <div class="rec-card {rec_class}">
        <div style="font-size:1.25rem;font-weight:700;margin-bottom:.4rem">{icon}</div>
        <div style="color:#333">{rec}</div>{period}
    </div>
    """, unsafe_allow_html=True)

    # ── KPI row ───────────────────────────────────────────────────────────────
    st.markdown('<div class="section-title">💰 財務指標サマリー</div>', unsafe_allow_html=True)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("キャップレート",
              f"{fin['cap_rate']:.2f}%",
              "良好" if fin['cap_rate'] >= 6 else ("普通" if fin['cap_rate'] >= 4 else "低"))
    coc_label = "キャッシュ収益率" if is_cash else "CoC リターン"
    k2.metric(coc_label,
              f"{fin['coc_return']:.2f}%",
              "高" if fin['coc_return'] >= 8 else ("中" if fin['coc_return'] >= 4 else "低"))
    k3.metric("月次CF（NOI）" if is_cash else "月次CF",
              usd(fin['monthly_cash_flow']),
              "プラス" if fin['monthly_cash_flow'] >= 0 else "マイナス")
    cash_label = "必要現金（全額）" if is_cash else "必要現金（頭金+諸費用）"
    k4.metric(cash_label, usd(fin['total_cash_needed']), jpy(fin['total_cash_needed'], rate))

    # ── Break-even rent ───────────────────────────────────────────────────────
    st.markdown('<div class="section-title">📉 損益分岐点分析</div>', unsafe_allow_html=True)
    be = calc_breakeven_rent(fin)
    if "error" not in be:
        b1, b2, b3, b4 = st.columns(4)
        b1.metric(
            "損益分岐点賃料",
            f"${be['breakeven_rent']:,.0f}/月",
            help="この賃料を下回るとキャッシュフローがマイナスになります",
        )
        b2.metric(
            "現在の賃料との差",
            f"${be['margin']:+,.0f}/月",
            "余裕あり ✅" if be["is_above_breakeven"] else "赤字 ❌",
        )
        b3.metric(
            "安全マージン",
            f"{be['margin_pct']:.1f}%",
            "十分" if be["margin_pct"] >= 15 else ("ギリギリ" if be["margin_pct"] >= 0 else "赤字"),
        )
        rent_zest = prop.get("rentZestimate")
        if rent_zest:
            diff     = fin["monthly_gross_income"] - rent_zest
            diff_pct = diff / rent_zest * 100
            b4.metric(
                "Zillow推定賃料との差",
                f"${diff:+,.0f}/月",
                f"Zestimate: ${rent_zest:,.0f}/月 ({diff_pct:+.1f}%)",
            )
        else:
            b4.metric("Zillow Rent Zestimate", "データなし", "")

    # ── 高度財務指標 ──────────────────────────────────────────────────────────
    st.markdown('<div class="section-title">🎯 高度財務指標</div>', unsafe_allow_html=True)
    st.caption("プロ投資家が使う主要指標でリターンと安全性を多角的に評価します")

    irr_data  = calc_irr(fin, sim, exit_cost_pct)
    dscr_data = calc_dscr(fin)
    pct_data  = calc_1pct_rule(fin)
    beo_data  = calc_breakeven_occupancy(fin)
    atcf_data = calc_after_tax_cf(fin, depr, tax_bracket)

    adv1, adv2, adv3 = st.columns(3)
    with adv1:
        html = '<div class="card"><h4>📈 リターン指標</h4>'
        if "error" not in irr_data:
            irr_color  = "#2e7d32" if irr_data["irr"] >= 12 else "#e65100" if irr_data["irr"] >= 8 else "#b71c1c"
            irr_label  = "優秀" if irr_data["irr"] >= 12 else "良好" if irr_data["irr"] >= 8 else "普通"
            em_label   = "優秀" if irr_data["equity_multiple"] >= 2.0 else "良好" if irr_data["equity_multiple"] >= 1.5 else "普通"
            html += f'<div class="row"><span class="row-label">IRR（10年出口想定）</span><span class="row-value" style="color:{irr_color}">{irr_data["irr"]:.1f}% ― {irr_label}</span></div>'
            html += f'<div class="row"><span class="row-label">Equity Multiple</span><span class="row-value">{irr_data["equity_multiple"]:.2f}× ― {em_label}</span></div>'
            html += f'<div class="row"><span class="row-label">出口エクイティ（10年後）</span><span class="row-value">${irr_data["exit_equity"]:,.0f}</span></div>'
            html += f'<div class="row"><span class="row-label">初期投資額</span><span class="row-value">${irr_data["initial_investment"]:,.0f}</span></div>'
            html += f'<div class="row"><span class="row-label">受取総額（CF＋出口）</span><span class="row-value">${irr_data["total_cash_received"]:,.0f}</span></div>'
        else:
            html += f'<div style="color:#999;font-size:.88rem">{irr_data["error"]}</div>'
        html += "</div>"
        st.markdown(html, unsafe_allow_html=True)

    with adv2:
        html = '<div class="card"><h4>🏦 安全性指標</h4>'
        if "error" not in dscr_data:
            if dscr_data.get("is_cash"):
                html += '<div class="row"><span class="row-label">DSCR（返済カバー率）</span><span class="row-value" style="color:#2e7d32">∞ ― 全キャッシュ</span></div>'
            else:
                dscr_color = "#2e7d32" if dscr_data["dscr"] >= 1.5 else "#e65100" if dscr_data["dscr"] >= 1.0 else "#b71c1c"
                dscr_icon  = "✅" if dscr_data["pass"] else "❌"
                html += f'<div class="row"><span class="row-label">DSCR（返済カバー率）</span><span class="row-value" style="color:{dscr_color}">{dscr_data["dscr"]:.2f} {dscr_icon} ― {dscr_data["label"]}</span></div>'
                html += f'<div class="row"><span class="row-label">年間NOI</span><span class="row-value">${dscr_data["annual_noi"]:,.0f}</span></div>'
                html += f'<div class="row"><span class="row-label">年間元利返済</span><span class="row-value">${dscr_data["annual_debt_service"]:,.0f}</span></div>'

        # Break-even occupancy
        if "error" not in beo_data:
            beo_color = "#2e7d32" if beo_data["pass"] else "#b71c1c"
            beo_icon  = "✅" if beo_data["pass"] else "⚠️"
            html += f'<div class="row"><span class="row-label">損益分岐稼働率</span><span class="row-value" style="color:{beo_color}">{beo_data["breakeven_occupancy_pct"]:.1f}% {beo_icon} ― {beo_data["label"]}</span></div>'
            html += f'<div class="row"><span class="row-label">許容空室率</span><span class="row-value">{beo_data["safe_vacancy_pct"]:.1f}%</span></div>'
        html += "</div>"
        st.markdown(html, unsafe_allow_html=True)

    with adv3:
        html = '<div class="card"><h4>💡 収益ルール・税引後</h4>'
        # 1% Rule
        pct_color = "#2e7d32" if pct_data["pass"] else "#e65100"
        pct_icon  = "✅ クリア" if pct_data["pass"] else "❌ 未達"
        html += f'<div class="row"><span class="row-label">1%ルール</span><span class="row-value" style="color:{pct_color}">{pct_data["ratio"]:.3f}% ― {pct_icon}</span></div>'
        html += f'<div class="row"><span class="row-label">　目標賃料（1%）</span><span class="row-value">${pct_data["target_rent"]:,.0f}/月</span></div>'
        html += f'<div class="row"><span class="row-label">　現在賃料との差</span><span class="row-value">${pct_data["gap"]:+,.0f}/月</span></div>'
        # After-Tax CF
        atcf_color = "#2e7d32" if atcf_data["after_tax_annual_cf"] >= 0 else "#b71c1c"
        html += f'<div class="row"><span class="row-label">税引後CF（年・税率{tax_bracket:.0f}%）</span><span class="row-value" style="color:{atcf_color}">${atcf_data["after_tax_annual_cf"]:,.0f}</span></div>'
        html += f'<div class="row"><span class="row-label">税引後CF（月）</span><span class="row-value" style="color:{atcf_color}">${atcf_data["after_tax_monthly_cf"]:,.0f}</span></div>'
        if atcf_data["tax_benefit"] > 0:
            html += f'<div class="row"><span class="row-label">　節税効果（減価償却等）</span><span class="row-value" style="color:#2e7d32">+${atcf_data["tax_benefit"]:,.0f}</span></div>'
        elif atcf_data["tax_owed"] > 0:
            html += f'<div class="row"><span class="row-label">　追加税負担</span><span class="row-value" style="color:#e65100">-${atcf_data["tax_owed"]:,.0f}</span></div>'
        html += "</div>"
        st.markdown(html, unsafe_allow_html=True)

    # ── Details grid ──────────────────────────────────────────────────────────
    st.markdown('<div class="section-title">📋 詳細データ</div>', unsafe_allow_html=True)
    d1, d2 = st.columns(2)

    with d1:
        rows = [("購入価格", f"{usd(fin['purchase_price'])} ({jpy(fin['purchase_price'], rate)})")]
        if is_cash:
            rows += [
                ("購入方法",     "💵 全キャッシュ"),
                ("諸費用",       usd(fin['closing_costs'])),
                ("必要現金合計", f"{usd(fin['total_cash_needed'])} ({jpy(fin['total_cash_needed'], rate)})"),
            ]
        else:
            rows += [
                ("購入方法",      "🏦 ローン（モーゲージ）"),
                ("頭金",          f"{usd(fin['down_payment'])} ({fin['down_payment_pct']:.0f}%)"),
                ("諸費用",        usd(fin['closing_costs'])),
                ("必要現金合計",  f"{usd(fin['total_cash_needed'])} ({jpy(fin['total_cash_needed'], rate)})"),
                ("ローン額",      usd(fin['loan_amount'])),
                ("金利/期間",     f"{fin['mortgage_rate']:.3f}% / {fin['loan_term_years']}年"),
                ("月次モーゲージ", usd(fin['monthly_mortgage'])),
            ]
        rows += [
            ("月次賃料収入",   usd(fin['monthly_gross_income'])),
            ("月次経費",       usd(fin['monthly_expenses'])),
            ("月次NOI",        usd(fin['monthly_noi'])),
            ("年間NOI",        usd(fin['annual_noi'])),
            ("年間CF",         usd(fin['annual_cash_flow'])),
            ("GRM（賃料乗数）", f"{fin['grm']:.1f}倍"),
            ("賃料/価格比",    f"{fin['rent_to_price']:.3f}%"),
        ]
        html = '<div class="card"><h4>💵 財務計算</h4>'
        for label, val in rows:
            html += (f'<div class="row"><span class="row-label">{label}</span>'
                     f'<span class="row-value">{val}</span></div>')
        html += "</div>"
        st.markdown(html, unsafe_allow_html=True)

    with d2:
        # 補完データ取得（Zillow不足時のフォールバック）
        ccad_d    = loc.get("ccad", {})    if not loc.get("error") else {}
        redfin_d2 = loc.get("redfin", {})  if not loc.get("error") else {}
        realtor_d2= loc.get("realtor", {}) if not loc.get("error") else {}
        ccad_ok   = ccad_d    and not ccad_d.get("error")
        redfin_ok = redfin_d2 and not redfin_d2.get("error")
        rltr_ok   = realtor_d2 and not realtor_d2.get("error")

        def _best(zillow_val, ccad_key, redfin_key, realtor_key=None):
            if zillow_val: return zillow_val
            if ccad_ok   and ccad_d.get(ccad_key):   return ccad_d[ccad_key]
            if redfin_ok and redfin_d2.get(redfin_key): return redfin_d2[redfin_key]
            if realtor_key and rltr_ok and realtor_d2.get(realtor_key): return realtor_d2[realtor_key]
            return None

        prop_rows = []
        if not prop.get("error") or ccad_ok or redfin_ok:
            home_type  = prop.get("homeType") or (redfin_d2.get("status") if redfin_ok else None)
            living_area= _best(prop.get("livingArea"), "sqft", "sqft", "sqft")
            lot_area   = prop.get("lotAreaValue")
            bedrooms   = _best(prop.get("bedrooms"),   None, "beds", "beds")
            bathrooms  = _best(prop.get("bathrooms"),  None, "baths", "baths")
            year_built = _best(prop.get("yearBuilt"),  "year_built", "year_built", "year_built")
            zestimate  = prop.get("zestimate")
            rent_zest  = prop.get("rentZestimate")
            last_sold_p= prop.get("lastSoldPrice")
            last_sold_d= prop.get("lastSoldDate", "")

            # データソース注記
            src_note = []
            if year_built and not prop.get("yearBuilt"):
                if ccad_ok and ccad_d.get("year_built") == year_built: src_note.append("築年: Collin CAD")
                elif redfin_ok: src_note.append("築年: Redfin")
            if living_area and not prop.get("livingArea"):
                if ccad_ok and ccad_d.get("sqft") == living_area: src_note.append("面積: Collin CAD")
                elif redfin_ok: src_note.append("面積: Redfin")

            if home_type:  prop_rows.append(("物件タイプ", home_type))
            if living_area: prop_rows.append(("広さ", f"{living_area:,} sq ft"))
            if lot_area:   prop_rows.append(("土地面積", f"{prop.get('lotAreaValue','N/A')} sq ft"))
            if bedrooms and bathrooms:
                prop_rows.append(("寝室/浴室", f"{bedrooms}床 / {bathrooms}浴"))
            if year_built: prop_rows.append(("築年", f"{year_built}年"))
            if zestimate:  prop_rows.append(("Zestimate", usd(zestimate)))
            if rent_zest:  prop_rows.append(("Rent Zestimate", f"{usd(rent_zest)}/月"))
            if last_sold_p: prop_rows.append(("最終売却", f"{usd(last_sold_p)} ({last_sold_d})"))
            if src_note:
                prop_rows.append(("📎 補完データ出典", " / ".join(src_note)))

            if rent_zest and fin.get("monthly_gross_income"):
                rz = rent_zest; ur = fin["monthly_gross_income"]
                diff_pct = (ur - rz) / rz * 100
                marker = "⬆️ 相場より高め" if diff_pct > 5 else "⬇️ 相場より低め" if diff_pct < -5 else "≈ 相場並み"
                prop_rows.append(("賃料市場比較", f"{marker} ({diff_pct:+.1f}%)"))

            # Collin CAD 固定資産評価 (TX only)
            if ccad_ok:
                prop_rows.append(("――――", ""))
                prop_rows.append(("📋 CAD市場評価額", usd(ccad_d["market_value"]) if ccad_d.get("market_value") else "N/A"))
                if ccad_d.get("imprv_value") and ccad_d.get("land_value"):
                    prop_rows.append(("　建物 / 土地", f"{usd(ccad_d['imprv_value'])} / {usd(ccad_d['land_value'])}"))
                if ccad_d.get("land_pct"):
                    prop_rows.append(("　土地割合（減価償却参考）", f"{ccad_d['land_pct']}%"))
                if ccad_d.get("pool"):
                    prop_rows.append(("プール", "あり 🏊"))

        html = '<div class="card"><h4>🏠 物件情報</h4>'
        if prop_rows:
            for label, val in prop_rows:
                if val in ("N/A", ""):
                    if label == "――――":
                        html += '<div style="border-top:1px solid #e8eaf6;margin:.4rem 0"></div>'
                    continue
                html += (f'<div class="row"><span class="row-label">{label}</span>'
                         f'<span class="row-value">{val}</span></div>')
        else:
            html += f'<div style="color:#999;font-size:.9rem">物件データ取得失敗: {prop.get("error","")}</div>'
        html += "</div>"
        st.markdown(html, unsafe_allow_html=True)

    # ── Price history ─────────────────────────────────────────────────────────
    price_history = prop.get("priceHistory", [])
    if price_history:
        st.markdown('<div class="section-title">📈 取引・価格履歴</div>', unsafe_allow_html=True)
        html = '<div class="card"><h4>🕐 過去の取引履歴</h4>'
        for ev in price_history[:8]:
            if ev.get("price"):
                html += (f'<div class="row"><span class="row-label">{ev.get("date","")} ― {ev.get("event","")}'
                         f'</span><span class="row-value">{usd(ev["price"])}</span></div>')
        html += "</div>"
        st.markdown(html, unsafe_allow_html=True)

    # ── Multi-source price comparison ─────────────────────────────────────────
    redfin_d  = loc.get("redfin",  {}) if not loc.get("error") else {}
    realtor_d = loc.get("realtor", {}) if not loc.get("error") else {}
    has_redfin  = redfin_d  and not redfin_d.get("error")
    has_realtor = realtor_d and not realtor_d.get("error")
    if has_redfin or has_realtor or prop.get("zestimate"):
        st.markdown('<div class="section-title">🏷️ 価格比較（複数データソース）</div>', unsafe_allow_html=True)
        st.caption("Zillow・Redfin・Realtor.com の推定価格と購入価格を比較します")

        sources = []
        # 購入価格（入力値）は常に表示
        sources.append({
            "label": "購入価格\n（入力値）",
            "price": fin["purchase_price"],
            "dom": None,
            "ppsf": None,
            "status": "入力値",
            "color": "#1a237e",
        })
        # Zillow Zestimate
        zest = prop.get("zestimate")
        if zest:
            sources.append({
                "label": "Zillow\nZestimate",
                "price": zest,
                "dom": None,
                "ppsf": None,
                "status": "推定価格",
                "color": "#006aff",
            })
        # Redfin
        if has_redfin:
            rf_price = redfin_d.get("list_price") or redfin_d.get("estimate")
            sources.append({
                "label": "Redfin",
                "price": rf_price,
                "dom":   redfin_d.get("days_on_market"),
                "ppsf":  redfin_d.get("price_per_sqft"),
                "status": redfin_d.get("status", ""),
                "color": "#d63f32",
            })
        # Realtor.com
        if has_realtor:
            rl_price = realtor_d.get("list_price") or realtor_d.get("estimate")
            sources.append({
                "label": "Realtor.com",
                "price": rl_price,
                "dom":   realtor_d.get("days_on_market"),
                "ppsf":  realtor_d.get("price_per_sqft"),
                "status": realtor_d.get("status", ""),
                "color": "#c0392b",
            })

        cols = st.columns(len(sources))
        for i, src in enumerate(sources):
            with cols[i]:
                lbl    = src["label"].replace("\n", "<br>")
                price  = src["price"]
                is_ref = (i == 0)  # 購入価格が基準
                html   = f'<div class="card" style="text-align:center">'
                html  += f'<div style="font-size:.82rem;font-weight:600;color:#555;margin-bottom:.4rem">{lbl}</div>'
                if price:
                    if is_ref:
                        html += f'<div style="font-size:1.4rem;font-weight:700;color:{src["color"]}">${price:,.0f}</div>'
                    else:
                        diff     = price - fin["purchase_price"]
                        diff_pct = diff / fin["purchase_price"] * 100
                        d_color  = "#2e7d32" if diff > 0 else "#b71c1c" if diff < 0 else "#555"
                        d_arrow  = "▲" if diff > 0 else "▼" if diff < 0 else "＝"
                        html += f'<div style="font-size:1.4rem;font-weight:700;color:{src["color"]}">${price:,.0f}</div>'
                        html += f'<div style="font-size:.8rem;color:{d_color};margin-top:.2rem">{d_arrow} {diff:+,.0f} ({diff_pct:+.1f}%)</div>'
                else:
                    html += '<div style="color:#aaa;font-size:.9rem;margin-top:.4rem">データなし</div>'
                if src["dom"] is not None:
                    html += f'<div style="font-size:.78rem;color:#777;margin-top:.4rem">📅 市場掲載 {src["dom"]}日</div>'
                if src["ppsf"]:
                    html += f'<div style="font-size:.78rem;color:#777">📐 ${src["ppsf"]:,.0f}/sqft</div>'
                if src["status"] and not is_ref:
                    html += f'<div style="font-size:.75rem;color:#aaa;margin-top:.2rem">{src["status"]}</div>'
                html += '</div>'
                st.markdown(html, unsafe_allow_html=True)

    # ── Location ──────────────────────────────────────────────────────────────
    st.markdown('<div class="section-title">📍 周辺環境・安全性</div>', unsafe_allow_html=True)

    if not loc.get("error"):

        # Walk Score バナー（設定済みの場合）
        walk = loc.get("walk_score", {})
        if walk and not walk.get("error"):
            ws  = walk.get("walk_score", 0)
            ts  = walk.get("transit_score")
            bs  = walk.get("bike_score")
            w_color = "#1565c0" if ws >= 70 else "#e65100" if ws >= 50 else "#b71c1c"
            walk_html = f"""
            <div style="background:#e3f2fd;border-left:4px solid #1565c0;border-radius:8px;
                        padding:.9rem 1.2rem;margin-bottom:1rem;display:flex;gap:2rem;align-items:center">
                <div><span style="font-size:1.5rem;font-weight:700;color:{w_color}">{ws}</span>
                     <span style="font-size:.82rem;color:#555;margin-left:.3rem">Walk Score<br>{walk.get("walk_desc","")}</span></div>
            """
            if ts is not None:
                t_color = "#2e7d32" if ts >= 70 else "#e65100" if ts >= 50 else "#b71c1c"
                walk_html += f'<div><span style="font-size:1.5rem;font-weight:700;color:{t_color}">{ts}</span><span style="font-size:.82rem;color:#555;margin-left:.3rem">Transit Score<br>{walk.get("transit_desc","")}</span></div>'
            if bs is not None:
                b_color = "#2e7d32" if bs >= 70 else "#e65100" if bs >= 50 else "#b71c1c"
                walk_html += f'<div><span style="font-size:1.5rem;font-weight:700;color:{b_color}">{bs}</span><span style="font-size:.82rem;color:#555;margin-left:.3rem">Bike Score<br>{walk.get("bike_desc","")}</span></div>'
            walk_html += "</div>"
            st.markdown(walk_html, unsafe_allow_html=True)

        # 洪水ゾーン バナー
        flood = loc.get("flood_zone", {})
        if flood and not flood.get("error"):
            fcolor = flood.get("color", "#f57f17")
            ficon  = "🚨" if flood.get("insurance_required") else "✅"
            fbg    = "#ffebee" if flood.get("insurance_required") else "#e8f5e9"
            st.markdown(f"""
            <div style="background:{fbg};border-left:4px solid {fcolor};border-radius:8px;
                        padding:.9rem 1.2rem;margin-bottom:1rem">
                <span style="font-weight:700;color:{fcolor};font-size:.95rem">
                    {ficon} 洪水リスク: ゾーン {flood.get('zone','X')} ― {flood.get('description','')}
                </span>
                {'<span style="font-size:.82rem;color:#b71c1c;margin-left:.8rem">⚠️ 洪水保険への加入が必須です（SFHA指定エリア）</span>' if flood.get('insurance_required') else ''}
                <span style="font-size:.78rem;color:#888;margin-left:.8rem">出典: FEMA NFHL</span>
            </div>
            """, unsafe_allow_html=True)

        la, lb, lc = st.columns(3)

        # 学校
        zillow_schools = prop.get("schools", [])
        google_schools = loc.get("schools", [])

        def place_card(col, title, items):
            h = f'<div class="card"><h4>{title}</h4>'
            if items:
                for p in items[:4]:
                    h += (f'<div class="row"><span class="row-label">{p["name"]}</span>'
                          f'<span class="row-value">{p["distance_miles"]}マイル</span></div>')
            else:
                h += '<div style="color:#999;font-size:.88rem">データなし</div>'
            h += "</div>"
            col.markdown(h, unsafe_allow_html=True)

        if zillow_schools:
            h = '<div class="card"><h4>🎓 学区・近隣の学校</h4>'
            for s in zillow_schools[:4]:
                name   = s.get("name", "")
                rating = s.get("rating", "")
                dist   = s.get("distance", "")
                level  = s.get("level", "")
                parts  = []
                if rating: parts.append(f"⭐{rating}/10")
                if dist:   parts.append(f"{dist}マイル")
                if level:  parts.append(level)
                detail = " · ".join(parts)
                h += (f'<div class="row"><span class="row-label">{name}</span>'
                      f'<span class="row-value">{detail}</span></div>')
            h += "</div>"
            la.markdown(h, unsafe_allow_html=True)
        else:
            place_card(la, "🎓 近隣の学校", google_schools)

        place_card(lb, "🛒 スーパー/食料品", loc.get("supermarkets", []))
        place_card(lc, "🏪 ショッピング",    loc.get("shopping", []))

        # SchoolDigger 学校評価（詳細）
        sd_schools = loc.get("school_ratings", [])
        if sd_schools:
            h = '<div class="card"><h4>🏆 学校評価（SchoolDigger）</h4>'
            for s in sd_schools[:4]:
                stars = s.get("rating")
                if stars is not None:
                    filled = int(round(stars))
                    star_str = "★" * filled + "☆" * (5 - filled) + f" {stars:.1f}/5"
                    s_color = "#2e7d32" if stars >= 3.5 else "#e65100" if stars >= 2.5 else "#b71c1c"
                else:
                    star_str = "評価なし"
                    s_color = "#aaa"
                rank_str = ""
                if s.get("rank") and s.get("rank_of"):
                    rank_str = f" ／ 州内{s['rank']:,}位/{s['rank_of']:,}校"
                h += (f'<div class="row"><span class="row-label">{s["name"]}'
                      f'<span style="font-size:.75rem;color:#888"> {s.get("grades","")}</span></span>'
                      f'<span class="row-value" style="color:{s_color}">{star_str}{rank_str}</span></div>')
            h += '<div style="font-size:.75rem;color:#aaa;margin-top:.4rem">出典: SchoolDigger.com</div></div>'
            la.markdown(h, unsafe_allow_html=True)

        # 詳細交通機関情報（OpenStreetMap Overpass）
        transit_det = loc.get("transit_detailed", {})
        if transit_det and not transit_det.get("error"):
            td_stops = transit_det.get("stops", [])
            car_dep  = transit_det.get("car_dependent", True)
            if car_dep:
                st.markdown("""
                <div style="background:#fff3e0;border-left:4px solid #e65100;border-radius:8px;
                            padding:.9rem 1.2rem;margin-top:.8rem">
                    <span style="font-weight:700;color:#e65100">🚗 自動車依存エリア</span>
                    <span style="font-size:.88rem;color:#555;margin-left:.6rem">
                        半径3マイル以内に公共交通機関の停留所なし（バス・鉄道・地下鉄）。
                        車なしでの生活は困難です。入居者層は自動車保有世帯が前提。
                    </span>
                    <span style="font-size:.75rem;color:#aaa;margin-left:.4rem">出典: OpenStreetMap</span>
                </div>
                """, unsafe_allow_html=True)
            else:
                h = '<div class="card"><h4>🚌 交通機関（OpenStreetMap）</h4>'
                for stop in td_stops[:5]:
                    h += (f'<div class="row"><span class="row-label">{stop["type"]} {stop["name"]}'
                          f'<span style="font-size:.78rem;color:#888"> {stop.get("operator","")}</span></span>'
                          f'<span class="row-value">{stop["distance_miles"]}マイル</span></div>')
                h += f'<div style="font-size:.75rem;color:#aaa;margin-top:.4rem">出典: OpenStreetMap / 半径{transit_det.get("radius_miles",1.9)}マイル</div></div>'
                lc.markdown(h, unsafe_allow_html=True)

        # 犯罪データ（Chicago Data Portal / FBI Crime Data Explorer）
        crime = loc.get("crime", {})
        if crime and not crime.get("error"):
            safety_score    = crime.get("safety_score", 0)
            safety_label    = crime.get("safety_label", "")
            total_incidents = crime.get("total_incidents", 0)
            year            = crime.get("year", "")
            top_crimes      = crime.get("top_crime_types", [])
            source          = crime.get("source", "")
            is_fbi          = "FBI" in source

            if safety_score >= 70:
                c_color, c_bg, c_icon = "#2e7d32", "#e8f5e9", "✅"
            elif safety_score >= 40:
                c_color, c_bg, c_icon = "#e65100", "#fff3e0", "⚠️"
            else:
                c_color, c_bg, c_icon = "#b71c1c", "#ffebee", "🚨"

            crimes_str = (" / ".join(f"{c['type']}({c['count']}件)" for c in top_crimes[:4])
                          if top_crimes else "データなし")

            if is_fbi:
                rate       = crime.get("crime_rate_per_1000", 0)
                total_v    = crime.get("total_violent", 0)
                total_p    = crime.get("total_property", 0)
                population = crime.get("population", 0)
                agency_nm  = crime.get("agency_name", "")
                detail_str = (f"暴力犯罪: {total_v:,}件 ／ 財産犯罪: {total_p:,}件 ／ "
                              f"犯罪率: {rate:.1f}件/千人 ／ 対象人口: {population:,}人")
                src_str    = f"{year}年 {agency_nm}（出典: FBI Crime Data Explorer）"
            else:
                radius_m   = crime.get("radius_meters", 800)
                detail_str = f"{year}年 半径{radius_m}m以内"
                src_str    = f"総件数: <strong>{total_incidents}件</strong>（出典: Chicago Data Portal）"

            st.markdown(f"""
            <div style="background:{c_bg};border-left:4px solid {c_color};border-radius:8px;
                        padding:1rem 1.2rem;margin-top:1rem">
                <div style="font-weight:700;color:{c_color};font-size:1rem">
                    {c_icon} 安全スコア: {safety_score}/100 ― {safety_label}
                </div>
                <div style="color:#555;font-size:.88rem;margin-top:.4rem">
                    {src_str}
                </div>
                <div style="color:#555;font-size:.85rem;margin-top:.3rem">
                    {detail_str}
                </div>
                <div style="color:#555;font-size:.85rem;margin-top:.3rem">
                    主な犯罪タイプ: {crimes_str}
                </div>
            </div>
            """, unsafe_allow_html=True)
        elif not crime or crime.get("error"):
            # 犯罪データなし → 人口統計ベースの安全性推定
            demo       = loc.get("demographics", {})
            pop_growth = loc.get("population_growth", {})
            if demo and not demo.get("error") and demo.get("median_income", 0) > 0:
                income      = demo.get("median_income", 0)
                vac_rate    = demo.get("vacancy_rate", 0)
                renter_pct  = demo.get("renter_pct", 0)
                # 推定安全スコア（全米中央所得$75k基準）
                est_safety = min(90, max(30,
                    50
                    + min(30, (income - 50000) / 2000)   # 高所得ほど高スコア
                    - min(15, vac_rate * 1.5)             # 高空室ほど低スコア
                ))
                est_label = "安全（推定）" if est_safety >= 70 else "普通（推定）" if est_safety >= 50 else "要確認（推定）"
                est_color = "#2e7d32" if est_safety >= 70 else "#e65100"
                county = pop_growth.get("county_name", "") if pop_growth and not pop_growth.get("error") else ""
                st.markdown(f"""
                <div style="background:#f3e5f5;border-left:4px solid #7b1fa2;border-radius:8px;
                            padding:1rem 1.2rem;margin-top:1rem">
                    <div style="font-weight:700;color:#7b1fa2;font-size:1rem">
                        📊 安全性 推定スコア: {int(est_safety)}/100 ― {est_label}
                    </div>
                    <div style="color:#555;font-size:.88rem;margin-top:.4rem">
                        ※ このエリアの直接犯罪データは未取得。世帯中央所得
                        <strong>${income:,}/年</strong>・空室率<strong>{vac_rate:.1f}%</strong>
                        から推定。{f'<strong>{county}</strong>は高所得・急成長郡。' if county else ''}
                    </div>
                    <div style="color:#888;font-size:.8rem;margin-top:.3rem">
                        正確な犯罪データには FBI_API_KEY の設定が必要です
                        （<a href="https://api.usa.gov/crime/fbi/sapi/" target="_blank">api.usa.gov/crime/fbi/sapi</a> で無料登録）
                    </div>
                </div>
                """, unsafe_allow_html=True)
            elif crime.get("error") and "未対応" not in crime.get("error", "") and "未設定" not in crime.get("error", ""):
                st.info(f"⚠️ 犯罪データ: {crime['error']}")

        road = loc.get("road_info", {})
        if road.get("road_name") and road["road_name"] != "不明":
            if road.get("is_major_road"):
                st.warning(f"⚠️ **道路情報**: 主要道路沿い（{road['road_name']}）― 騒音・安全性に注意")
            else:
                st.success(f"✅ **道路情報**: 住宅街区内の静かな道路（{road['road_name']}）")

        # Census 人口統計 + 郡人口増加
        demo       = loc.get("demographics", {})
        pop_growth = loc.get("population_growth", {})
        if demo and not demo.get("error"):
            st.markdown('<div class="section-title">🏘️ 近隣統計情報（US Census ACS）</div>', unsafe_allow_html=True)
            dem1, dem2, dem3, dem4 = st.columns(4)
            dem1.metric("世帯中央所得", f"${demo.get('median_income', 0):,.0f}/年",
                        "高所得エリア" if demo.get("median_income", 0) >= 80000 else "標準エリア")
            dem2.metric("総人口", f"{demo.get('total_population', 0):,}人", demo.get("name", ""))
            dem3.metric("空室率", f"{demo.get('vacancy_rate', 0):.1f}%",
                        "低空室（需要高）" if demo.get("vacancy_rate", 0) < 8 else "要確認")
            dem4.metric("借家比率", f"{demo.get('renter_pct', 0):.1f}%",
                        "賃貸需要高" if demo.get("renter_pct", 0) >= 40 else "持家エリア")

        # 郡レベル人口増加トレンド
        if pop_growth and not pop_growth.get("error"):
            g2 = pop_growth.get("growth_2yr_pct", 0)
            g1 = pop_growth.get("growth_1yr_pct", 0)
            g2_color = "#2e7d32" if g2 >= 3 else "#e65100" if g2 >= 0 else "#b71c1c"
            g1_color = "#2e7d32" if g1 >= 1.5 else "#e65100" if g1 >= 0 else "#b71c1c"
            g2_label = "急成長 🚀" if g2 >= 5 else "成長中 ✅" if g2 >= 3 else "緩成長 ➡️" if g2 >= 0 else "人口減少 ⚠️"
            g1_label = "高成長" if g1 >= 3 else "成長中" if g1 >= 1.5 else "横ばい" if g1 >= 0 else "減少"
            pg1, pg2, pg3, pg4 = st.columns(4)
            pg1.metric("郡名", pop_growth.get("county_name", ""), "Census PEP 2022")
            pg2.metric("2022年人口", f"{pop_growth.get('pop_2022', 0):,}人", "")
            pg3.metric("2年間成長率（2020→2022）",
                       f"{g2:+.1f}%",
                       g2_label)
            pg4.metric("直近1年成長率（2021→2022）",
                       f"{g1:+.1f}%",
                       g1_label)
            # 成長率グラフバー
            bar_color = "#1b5e20" if g2 >= 5 else "#43a047" if g2 >= 3 else "#fb8c00" if g2 >= 0 else "#e53935"
            bar_width = min(abs(g2) * 8, 100)
            st.markdown(f"""
            <div style="background:#f5f5f5;border-radius:8px;padding:.8rem 1rem;margin-top:.5rem">
                <div style="font-size:.85rem;color:#555;margin-bottom:.4rem">
                    📈 <strong>{pop_growth.get('county_name','')}</strong> 人口増加トレンド
                    <span style="font-size:.75rem;color:#aaa;margin-left:.5rem">出典: US Census Bureau Population Estimates</span>
                </div>
                <div style="display:flex;align-items:center;gap:.8rem">
                    <div style="width:{bar_width}%;height:18px;background:{bar_color};border-radius:4px;min-width:4px"></div>
                    <span style="font-size:.9rem;font-weight:700;color:{g2_color}">2年間 {g2:+.1f}% ({g2_label})</span>
                </div>
                <div style="font-size:.78rem;color:#777;margin-top:.3rem">
                    人口密度: {pop_growth.get('density', 0):.1f}人/sq mi ／
                    2020年: {pop_growth.get('pop_2020', 0):,}人 →
                    2021年: {pop_growth.get('pop_2021', 0):,}人 →
                    2022年: {pop_growth.get('pop_2022', 0):,}人
                </div>
            </div>
            """, unsafe_allow_html=True)

    else:
        st.info(f"周辺環境データ取得失敗: {loc.get('error')}")

    # ── Sensitivity analysis ──────────────────────────────────────────────────
    st.markdown('<div class="section-title">🌡️ 感度分析（What-If シナリオ）</div>', unsafe_allow_html=True)
    st.caption("賃料と購入価格がそれぞれ変動した場合の月次キャッシュフロー（緑=プラス・赤=マイナス）")
    st.plotly_chart(sensitivity_chart_rental(fin), use_container_width=True)

    # ── 10-year simulation ────────────────────────────────────────────────────
    st.markdown(
        f'<div class="section-title">📈 10年間 投資シミュレーション'
        f'（賃料+{rent_growth:.1f}%/年・価格+{appreciation:.1f}%/年）</div>',
        unsafe_allow_html=True,
    )
    st.plotly_chart(ten_year_chart(sim), use_container_width=True)

    sim_df = pd.DataFrame(sim).copy()
    for col in ["物件価値", "月額賃料", "年間NOI", "年間CF", "累積CF", "ローン残高", "エクイティ", "総リターン"]:
        sim_df[col] = sim_df[col].apply(lambda x: f"${x:,.0f}")
    st.dataframe(sim_df, use_container_width=True, hide_index=True)

    # ── Depreciation ──────────────────────────────────────────────────────────
    st.markdown('<div class="section-title">🏛️ 減価償却・節税効果（日本人投資家向け）</div>', unsafe_allow_html=True)
    dep1, dep2, dep3 = st.columns(3)
    dep1.metric("年間減価償却費", f"${depr['annual_depreciation']:,.0f}",
                f"月額 ${depr['monthly_depreciation']:,.0f}")
    dep2.metric("償却対象額（建物）", usd(depr["depreciable_basis"]),
                f"土地 {land_pct:.0f}% を除外")
    dep3.metric("償却期間", "27.5年（米国住宅）", "定額法 Straight-line")

    st.markdown("**税率別 年間節税効果（概算）**")
    tax_cols = st.columns(4)
    for i, (rate_pct, savings) in enumerate(depr["tax_savings"].items()):
        tax_cols[i].metric(f"税率 {rate_pct}%", f"${savings:,.0f}/年", f"月額 ${savings/12:,.0f}")

    with st.expander("📌 減価償却・税務の注意点（日本人投資家向け）", expanded=False):
        st.markdown("""
**アメリカでの減価償却（Depreciation）**
- 住宅用不動産：27.5年 定額償却（Straight-line method）
- 土地は償却不可（通常、物件価格の15〜25%が土地価値）
- 年間の家賃収入からこの金額を費用計上でき、課税所得を圧縮できます

**パッシブ・アクティビティ・ロス（PAL）ルール**
- 不動産賃貸収入はパッシブ所得に分類されます
- 損失（ネガティブCF + 減価償却）は原則として他のパッシブ所得とのみ相殺可能
- AGI（調整後総所得）が$100,000以下の場合：最大$25,000まで通常所得と相殺可能
- 不動産専業家（Real Estate Professional）認定を受ければ制限なし

**売却時の注意点（Depreciation Recapture）**
- 売却時に過去の減価償却分は**25%の税率**で「回収課税」されます
- 長期譲渡所得税（0/15/20%）とは別に課税されます

**日米租税条約・FIRPTA**
- 外国人（日本人）の不動産売却益は FIRPTA（15%源泉徴収）の対象
- 日本での確定申告でも申告が必要（外国税額控除を活用）
- 専門家（米国CPA / Tax Attorney）への相談を強く推奨します
        """)

    # ── Market context (FRED + BLS + HUD FMR) ────────────────────────────────
    st.markdown('<div class="section-title">📊 マーケット・コンテキスト</div>', unsafe_allow_html=True)

    mc1, mc2 = st.columns([2, 1])

    with mc1:
        # FRED 住宅ローン金利チャート
        if market_data:
            rate_fig = mortgage_rate_chart(market_data)
            if rate_fig:
                st.plotly_chart(rate_fig, use_container_width=True)
            else:
                rates_data = market_data.get("mortgage_rates", {})
                if rates_data.get("error"):
                    st.caption(f"📉 金利データ: {rates_data['error']}")

    with mc2:
        # BLS 失業率
        unemp = loc.get("unemployment", {}) if not loc.get("error") else {}
        if unemp and not unemp.get("error"):
            u_rate = unemp.get("unemployment_rate", 0)
            u_color = "#2e7d32" if u_rate < 4 else "#e65100" if u_rate < 6 else "#b71c1c"
            st.markdown(f"""
            <div class="card"><h4>📊 雇用状況（BLS）</h4>
            <div class="row"><span class="row-label">州失業率</span>
            <span class="row-value" style="color:{u_color}">{u_rate:.1f}% （{unemp.get('period','')}）</span></div>
            <div class="row"><span class="row-label">評価</span>
            <span class="row-value">{'低失業率 ✅' if u_rate < 4 else '標準 ✅' if u_rate < 6 else '要注意 ⚠️'}</span></div>
            <div style="font-size:.75rem;color:#aaa;margin-top:.5rem">出典: Bureau of Labor Statistics</div>
            </div>
            """, unsafe_allow_html=True)
        elif unemp.get("error"):
            st.caption(f"失業率データ: {unemp['error']}")

        # FRED 賃貸空室率
        vacancy_data = market_data.get("rental_vacancy", {}) if market_data else {}
        if vacancy_data and not vacancy_data.get("error"):
            vac_html = '<div class="card"><h4>🏘️ 賃貸空室率（FRED）</h4>'
            for sid, info in vacancy_data.items():
                if isinstance(info, dict) and "latest" in info:
                    v = info["latest"]
                    v_color = "#2e7d32" if v < 6 else "#e65100" if v < 10 else "#b71c1c"
                    v_label = "低空室（需要旺盛）" if v < 6 else "標準" if v < 10 else "高空室（供給過剰）"
                    vac_html += (f'<div class="row"><span class="row-label">{info["label"]}</span>'
                                 f'<span class="row-value" style="color:{v_color}">'
                                 f'{v:.1f}% ― {v_label}</span></div>')
            vac_html += '<div style="font-size:.75rem;color:#aaa;margin-top:.5rem">出典: FRED / Federal Reserve</div></div>'
            st.markdown(vac_html, unsafe_allow_html=True)

        # HUD Fair Market Rent
        hud = loc.get("hud_fmr", {}) if not loc.get("error") else {}
        if hud and not hud.get("error"):
            hud_html = f'<div class="card"><h4>🏛️ HUD 公正市場賃料 ({hud.get("year","")})</h4>'
            hud_html += f'<div style="font-size:.82rem;color:#555;margin-bottom:.5rem">{hud.get("area_name","")}</div>'
            has_data = False
            for label, key in [("スタジオ", "studio"), ("1BR", "1br"), ("2BR", "2br"), ("3BR", "3br"), ("4BR", "4br")]:
                val = hud.get(key, 0)
                if val:
                    has_data = True
                    curr = fin["monthly_gross_income"]
                    diff = curr - val
                    diff_str = f"（設定賃料比 {diff:+,.0f}）"
                    hud_html += f'<div class="row"><span class="row-label">{label}</span><span class="row-value">${val:,.0f}/月 <span style="font-size:.8rem;color:#888">{diff_str}</span></span></div>'
            if not has_data:
                hud_html += '<div style="color:#999;font-size:.88rem">賃料データなし（エリア未対応の可能性）</div>'
            hud_html += '<div style="font-size:.75rem;color:#aaa;margin-top:.5rem">出典: HUD Fair Market Rents</div></div>'
            st.markdown(hud_html, unsafe_allow_html=True)
        elif hud.get("error"):
            st.caption(f"HUD FMRデータ: {hud['error']}")

    # ── Local News & Development Intelligence ────────────────────────────────
    news = loc.get("local_news", {}) if not loc.get("error") else {}
    articles = news.get("articles", []) if news else []
    if articles:
        city_n  = news.get("city", "")
        state_n = news.get("state", "")
        pos_cnt = news.get("positive_count", 0)
        total_n = news.get("total_found", len(articles))

        st.markdown('<div class="section-title">📰 地域ニュース・開発動向</div>', unsafe_allow_html=True)
        st.caption(
            f"「{city_n}, {state_n}」エリアの不動産開発・投資関連ニュース "
            f"（ポジティブ優先 {pos_cnt}件 / 取得総数 {total_n}件 ｜ "
            f"出典: Google News / GDELT Project）"
        )

        num_show = min(len(articles), 6)
        ncols    = min(num_show, 3)
        if ncols > 0:
            cols = st.columns(ncols)
            for i, art in enumerate(articles[:num_show]):
                col  = cols[i % ncols]
                ttl  = art.get("title", "")
                url  = art.get("url", "")
                date = art.get("date", "")
                src  = art.get("source", "")
                summ = art.get("summary", "")[:160]

                link_html = (
                    f'<a href="{url}" target="_blank" rel="noopener" '
                    f'style="color:#1a237e;text-decoration:none;font-weight:600;'
                    f'font-size:.88rem;line-height:1.35">{ttl}</a>'
                    if url else
                    f'<span style="font-weight:600;font-size:.88rem">{ttl}</span>'
                )
                meta = []
                if date: meta.append(f"📅 {date}")
                if src:  meta.append(src)
                meta_str = " · ".join(meta)

                col.markdown(
                    f"""<div style="background:white;border:1px solid #e8eaf6;
                        border-left:4px solid #3949ab;border-radius:10px;
                        padding:.9rem 1.1rem;margin-bottom:.7rem;min-height:110px">
                        {link_html}
                        <div style="font-size:.75rem;color:#888;margin-top:.35rem">{meta_str}</div>
                        {('<div style="font-size:.8rem;color:#555;margin-top:.35rem">'
                          + summ + ('…' if len(art.get('summary','')) > 160 else '')
                          + '</div>') if summ else ''}
                    </div>""",
                    unsafe_allow_html=True,
                )

        if len(articles) > 6:
            with st.expander(f"📋 さらに {len(articles) - 6} 件のニュースを表示"):
                for art in articles[6:]:
                    ttl = art.get("title", "")
                    url = art.get("url", "")
                    src = art.get("source", "")
                    date = art.get("date", "")
                    if url:
                        st.markdown(f"🔗 [{ttl}]({url})&ensp;—&ensp;{date}  *{src}*")
                    else:
                        st.markdown(f"📰 {ttl}&ensp;—&ensp;{date}  *{src}*")

    # ── Industry / Market News ────────────────────────────────────────────────
    if industry_news and (
        industry_news.get("market_news")
        or industry_news.get("investment_news")
        or industry_news.get("japanese_news")
    ):
        mkt_arts  = industry_news.get("market_news",     [])
        inv_arts  = industry_news.get("investment_news", [])
        jp_arts   = industry_news.get("japanese_news",   [])
        total_n   = industry_news.get("total_found", 0)
        src_label = industry_news.get("source", "")

        st.markdown('<div class="section-title">🌐 業界ニュース・マーケットインサイト</div>',
                    unsafe_allow_html=True)
        st.caption(f"米国不動産市場の最新動向（取得 {total_n}件 ｜ 出典: {src_label}）")

        tab_labels = []
        if mkt_arts:  tab_labels.append("🏠 不動産・住宅市場")
        if inv_arts:  tab_labels.append("💰 投資・ディール情報")
        if jp_arts:   tab_labels.append("🇯🇵 日本語ニュース")

        if tab_labels:
            tabs = st.tabs(tab_labels)
            tab_idx = 0

            def _news_cards(container, articles, n_cols=3):
                n = min(len(articles), 6)
                if n == 0:
                    container.info("ニュースデータなし")
                    return
                cols = container.columns(min(n, n_cols))
                for i, art in enumerate(articles[:n]):
                    col  = cols[i % n_cols]
                    ttl  = art.get("title", "")
                    url  = art.get("url", "")
                    date = art.get("date", "")
                    src  = art.get("source", "")
                    summ = art.get("summary", "")[:160]
                    lang = art.get("lang", "")

                    border_col = "#1565c0" if lang == "ja" else "#c62828" if "bloomberg" in src.lower() or "wsj" in src.lower() else "#2e7d32"
                    link_html = (
                        f'<a href="{url}" target="_blank" rel="noopener" '
                        f'style="color:#1a237e;text-decoration:none;font-weight:600;'
                        f'font-size:.86rem;line-height:1.35">{ttl}</a>'
                        if url else
                        f'<span style="font-weight:600;font-size:.86rem">{ttl}</span>'
                    )
                    meta = []
                    if date: meta.append(f"📅 {date}")
                    if src:  meta.append(src)

                    col.markdown(
                        f"""<div style="background:white;border:1px solid #e8eaf6;
                            border-left:4px solid {border_col};border-radius:10px;
                            padding:.85rem 1rem;margin-bottom:.65rem;min-height:115px">
                            {link_html}
                            <div style="font-size:.73rem;color:#888;margin-top:.3rem">
                                {" · ".join(meta)}
                            </div>
                            {('<div style="font-size:.78rem;color:#555;margin-top:.3rem">'
                              + summ + ('…' if len(art.get('summary','')) > 160 else '')
                              + '</div>') if summ else ''}
                        </div>""",
                        unsafe_allow_html=True,
                    )
                if len(articles) > 6:
                    with container.expander(f"さらに {len(articles)-6} 件を表示"):
                        for art in articles[6:]:
                            ttl  = art.get("title", "")
                            url  = art.get("url", "")
                            src  = art.get("source", "")
                            date = art.get("date", "")
                            if url:
                                st.markdown(f"🔗 [{ttl}]({url}) — {date}  *{src}*")
                            else:
                                st.markdown(f"📰 {ttl} — {date}  *{src}*")

            if mkt_arts:
                _news_cards(tabs[tab_idx], mkt_arts)
                tab_idx += 1
            if inv_arts:
                _news_cards(tabs[tab_idx], inv_arts)
                tab_idx += 1
            if jp_arts:
                _news_cards(tabs[tab_idx], jp_arts)

    # ── Strengths & Risks ─────────────────────────────────────────────────────
    st.markdown('<div class="section-title">⚖️ 強みとリスク</div>', unsafe_allow_html=True)
    s1, s2 = st.columns(2)

    with s1:
        html = '<div class="card"><h4>✅ 投資の強み</h4>'
        for item in analysis.get("strengths", []):
            html += f'<span class="tag-good">✅ {item}</span>'
        html += "</div>"
        st.markdown(html, unsafe_allow_html=True)

    with s2:
        html = '<div class="card"><h4>⚠️ リスク要因</h4>'
        for item in analysis.get("risks", []):
            html += f'<span class="tag-risk">⚠️ {item}</span>'
        html += "</div>"
        st.markdown(html, unsafe_allow_html=True)

    # ── AI analysis ───────────────────────────────────────────────────────────
    st.markdown('<div class="section-title">🤖 AIコンサルタント詳細分析</div>', unsafe_allow_html=True)

    sections = [
        ("💵 財務分析",                            "financial_analysis",  True),
        ("📍 立地・市場分析",                       "location_analysis",   True),
        ("🔮 市場見通し",                           "market_outlook",      False),
        ("💡 総合評価・推奨アクション",             "overall_comment",     True),
        ("📌 具体的アクションプラン",               "action_plan",         False),
        ("🏛️ 税務上の考慮事項（日本人投資家向け）", "tax_considerations",  False),
    ]
    for title, key, expanded in sections:
        content = analysis.get(key, "")
        if content:
            with st.expander(title, expanded=expanded):
                st.write(content)

    # ── Disclaimer ────────────────────────────────────────────────────────────
    st.markdown("""
    <div class="disclaimer">
    <strong>⚠️ 免責事項</strong><br>
    本ツールはAIによる参考情報の提供を目的としており、投資判断の唯一の根拠として使用しないでください。
    不動産投資にはリスクが伴います。過去の取引履歴・価格データは将来の結果を保証するものではありません。
    投資判断の前に、米国不動産専門家（Realtor / Broker）・不動産弁護士・公認会計士・ファイナンシャルアドバイザーに
    必ずご相談ください。本ツールが提供する情報の正確性・完全性・最新性について一切の保証をいたしません。
    </div>
    """, unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    st.markdown("""
    <div class="main-header">
        <h1>🏠 AI不動産投資コンサルタント</h1>
        <p>日本人投資家向け 米国不動産 投資分析プラットフォーム</p>
        <p style="font-size:.82rem;opacity:.7;margin-top:.4rem">Powered by Claude AI · Google Maps · Zillow · FEMA · Census · FRED</p>
    </div>
    """, unsafe_allow_html=True)

    # ── Session state ─────────────────────────────────────────────────────────
    if "comparison_list" not in st.session_state:
        st.session_state.comparison_list = []

    # ── Sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### ⚙️ 基本設定")
        usd_to_jpy = st.number_input("USD/JPY レート", 100.0, 200.0, 150.0, 0.5)
        expense_ratio = st.slider(
            "運営経費率 (%)", 25, 55, 40,
            help="賃料収入に対する経費率（修繕・管理・空室損失・保険・固定資産税等）",
        )
        closing_pct = st.slider(
            "諸費用率 (%)", 1, 6, 3,
            help="購入価格に対する諸費用（タイトル保険・ローン手数料・登記等）",
        )
        st.divider()
        st.markdown("### 📈 シミュレーション設定")
        rent_growth = st.slider(
            "賃料上昇率 (%/年)", 0.0, 8.0, 3.0, 0.5,
            help="10年シミュレーションで使用する年間賃料上昇率",
        )
        appreciation = st.slider(
            "価格上昇率 (%/年)", 0.0, 8.0, 3.0, 0.5,
            help="10年シミュレーションで使用する年間価格上昇率",
        )
        land_pct = st.slider(
            "土地割合 (%)", 10, 40, 20, 5,
            help="物件価格に占める土地の割合（減価償却計算に使用 — 土地は償却不可）",
        )
        st.divider()
        st.markdown("### 💡 高度指標設定")
        tax_bracket = st.slider(
            "適用税率 (%)", 10, 45, 25, 5,
            help="税引後CFの計算に使用する所得税率（連邦＋州の合計目安）",
        )
        exit_cost_pct = st.slider(
            "出口コスト率 (%)", 3.0, 10.0, 6.0, 0.5,
            help="10年後売却時の仲介手数料・諸費用（IRR計算用）",
        )
        st.divider()
        st.markdown("""
**📊 指標の目安**
| 指標 | 優良 | 標準 | 要注意 |
|---|---|---|---|
| Cap Rate | ≥6% | 4-6% | <4% |
| CoC Return | ≥8% | 4-8% | <4% |
| DSCR | ≥1.5 | 1.25-1.5 | <1.25 |
| IRR | ≥12% | 8-12% | <8% |
| 1%ルール | ≥1% | — | <1% |
        """)
        st.divider()
        st.markdown("**🔑 API 設定確認**")
        st.markdown(f"Zillow (RapidAPI): {'✅' if os.getenv('RAPIDAPI_KEY') else '❌ 未設定'}")
        st.markdown(f"Google Maps:       {'✅' if os.getenv('GOOGLE_MAPS_API_KEY') else '❌ 未設定'}")
        st.markdown(f"Anthropic Claude:  {'✅' if os.getenv('ANTHROPIC_API_KEY') else '❌ 未設定'}")
        st.markdown(f"FRED (金利):       {'✅' if os.getenv('FRED_API_KEY') else '⚪ 未設定'}")
        st.markdown(f"Census (統計):     {'✅' if os.getenv('CENSUS_API_KEY') else '⚪ 未設定'}")
        st.markdown(f"HUD (FMR):         {'✅' if os.getenv('HUD_API_TOKEN') else '⚪ 未設定'}")
        st.markdown(f"Walk Score:        {'✅' if os.getenv('WALKSCORE_API_KEY') else '⚪ 未設定'}")

    # ── Comparison list (always visible at top) ───────────────────────────────
    if st.session_state.comparison_list:
        st.markdown('<div class="section-title">📊 物件比較リスト</div>', unsafe_allow_html=True)
        comp_df = pd.DataFrame(st.session_state.comparison_list)
        st.dataframe(comp_df, use_container_width=True, hide_index=True)
        if st.button("🗑️ 比較リストをクリア", key="clear_comp"):
            st.session_state.comparison_list = []
            st.rerun()
        st.divider()

    # ── Input form ────────────────────────────────────────────────────────────
    st.markdown('<div class="section-title">🔍 物件情報入力</div>', unsafe_allow_html=True)

    purchase_type = st.radio(
        "購入方法",
        ["🏦 ローン（モーゲージ）", "💵 全キャッシュ"],
        horizontal=True,
        key="purchase_type",
    )
    is_cash = (purchase_type == "💵 全キャッシュ")

    with st.form("form"):
        col_a, col_b = st.columns([2, 1])
        with col_a:
            address = st.text_input(
                "物件住所（英語）",
                placeholder="例: 1234 Oak Street, Austin, TX 78701",
                help="番地・通り名・市・州・郵便番号を含むフルアドレスを入力",
            )
        with col_b:
            purchase_price = st.number_input("購入価格 ($)", 50_000, 10_000_000, 450_000, 5_000, format="%d")

        if is_cash:
            st.markdown("#### 💵 キャッシュ購入 ― 収益条件")
            cc1, cc2 = st.columns(2)
            with cc1: monthly_rent = st.number_input("予想月額賃料 ($)", 500, 30_000, 2_400, 50)
            with cc2: hoa          = st.number_input("HOA/管理費 ($/月)", 0, 3_000, 0, 25)
            down_pct = 100
            rate     = 0.0
            term     = 30
        else:
            st.markdown("#### 🏦 ローン・収益条件")
            c1, c2, c3, c4, c5 = st.columns(5)
            with c1: down_pct     = st.slider("頭金 (%)", 10, 50, 25)
            with c2: rate         = st.number_input("金利 (%)", 1.0, 15.0, 7.0, 0.125, format="%.3f")
            with c3: term         = st.selectbox("期間", [30, 20, 15], format_func=lambda x: f"{x}年")
            with c4: monthly_rent = st.number_input("予想月額賃料 ($)", 500, 30_000, 2_400, 50)
            with c5: hoa          = st.number_input("HOA/管理費 ($/月)", 0, 3_000, 0, 25)

        submitted = st.form_submit_button("🔍 投資分析を開始する", use_container_width=True)

    if not submitted:
        if is_cash:
            st.info("💵 全キャッシュ購入モード：住所・購入価格・予想賃料を入力して分析を開始してください。")
        else:
            st.info("🏦 ローン購入モード：住所と財務条件を入力して「投資分析を開始する」ボタンを押してください。")
        return

    if not address.strip():
        st.error("物件住所を入力してください。")
        return

    fin = calc_financials(purchase_price, down_pct, closing_pct, monthly_rent,
                          expense_ratio, rate, term, hoa, is_cash)

    # ── Run analysis ──────────────────────────────────────────────────────────
    progress = st.progress(0)
    status   = st.empty()

    try:
        from fetcher import PropertyDataFetcher
        from analyzer import PropertyAnalyzer

        fetcher  = PropertyDataFetcher()
        analyzer = PropertyAnalyzer()

        status.markdown("🏠 **Zillowから物件データを取得中…**")
        prop_data = fetcher.get_property_data(address)
        progress.progress(20)

        status.markdown("📍 **Google Maps・Redfin・Realtor.com・各種APIで周辺環境を分析中…**")
        loc_data = fetcher.get_all_location_data(address)
        progress.progress(50)

        status.markdown("📰 **地域ニュース・開発動向を収集中（Google News / GDELT）…**")
        try:
            _pg   = loc_data.get("population_growth", {}) or {}
            news_data = fetcher.get_local_news(
                city    = loc_data.get("city",    ""),
                state   = loc_data.get("state",   ""),
                zipcode = loc_data.get("zipcode", ""),
                county  = _pg.get("county_name",  ""),
            )
            loc_data["local_news"] = news_data
        except Exception:
            loc_data["local_news"] = {"articles": [], "error": "ニュース取得失敗"}
        progress.progress(60)

        # 業界ニュースはセッション内でキャッシュ（毎回の物件分析で再取得しない）
        if "industry_news" not in st.session_state:
            status.markdown(
                "🌐 **業界ニュースを収集中"
                "（CNBC / Bloomberg / WSJ / NYT / Redfin / The Real Deal）…**"
            )
            try:
                st.session_state.industry_news = fetcher.get_industry_news()
            except Exception:
                st.session_state.industry_news = {}
        industry_news = st.session_state.get("industry_news", {})
        progress.progress(70)

        status.markdown("📊 **金融市場データを取得中（FRED）…**")
        try:
            market_data = fetcher.get_market_data(state=loc_data.get("state", ""))
        except TypeError:
            market_data = fetcher.get_market_data()
        progress.progress(80)

        status.markdown("🤖 **Claude AIが投資分析を実行中…**")
        analysis = analyzer.analyze_property(
            prop_data, loc_data, fin, market_data, industry_news
        )
        progress.progress(100)

        status.empty()
        progress.empty()

        if analysis.get("error") and not analysis.get("investment_score"):
            st.error(f"AI分析エラー: {analysis['error']}")
            return

        st.success(f"✅ 分析完了: **{address}**")
        show_results(
            analysis, prop_data, loc_data, fin, usd_to_jpy,
            rent_growth, appreciation, land_pct,
            tax_bracket, exit_cost_pct, market_data, industry_news,
        )

        # ── Add to comparison list ─────────────────────────────────────────
        st.divider()
        if st.button("📊 この物件を比較リストに追加", key="add_comp", use_container_width=False):
            irr_d = calc_irr(fin, calc_10year_simulation(fin, rent_growth, appreciation), exit_cost_pct)
            entry = {
                "住所":       address[:45] + ("…" if len(address) > 45 else ""),
                "スコア":     analysis.get("investment_score", 0),
                "Cap Rate":   f"{fin['cap_rate']:.2f}%",
                "CoC":        f"{fin['coc_return']:.2f}%",
                "月次CF":     f"${fin['monthly_cash_flow']:,.0f}",
                "IRR":        f"{irr_d.get('irr', 0):.1f}%" if "error" not in irr_d else "N/A",
                "購入価格":   f"${fin['purchase_price']:,.0f}",
                "推奨":       analysis.get("recommendation", ""),
            }
            already = any(e["住所"] == entry["住所"] for e in st.session_state.comparison_list)
            if not already:
                st.session_state.comparison_list.append(entry)
                st.success("✅ 比較リストに追加しました。ページ上部で確認できます。")
            else:
                st.info("すでに比較リストに追加済みです。")

    except Exception as e:
        progress.empty()
        status.empty()
        st.error(f"エラーが発生しました: {e}")
        st.exception(e)


if __name__ == "__main__":
    main()
