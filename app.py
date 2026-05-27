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
        down       = purchase_price   # 全額キャッシュ
        loan       = 0.0
        mortgage   = 0.0
        cash_needed = purchase_price + closing
        eff_down_pct = 100.0
    else:
        down       = purchase_price * (down_pct / 100)
        loan       = purchase_price - down
        cash_needed = down + closing
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
# 追加計算関数
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
        "land_value":          land_val,
        "land_pct":            land_pct,
        "depreciable_basis":   depr_basis,
        "annual_depreciation": annual_depr,
        "monthly_depreciation": annual_depr / 12,
        "tax_savings":         {r: annual_depr * r / 100 for r in [20, 25, 30, 37]},
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
        "breakeven_rent":    be_rent,
        "current_rent":      curr,
        "margin":            margin,
        "margin_pct":        (margin / be_rent * 100) if be_rent > 0 else 0,
        "is_above_breakeven": margin >= 0,
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
                {"range": [0, 50],  "color": "#ffebee"},
                {"range": [50, 65], "color": "#fff3e0"},
                {"range": [65, 80], "color": "#e8f5e9"},
                {"range": [80, 100],"color": "#e0f2f1"},
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
    pcts = [v / m * 100 if m else 0 for v, m in zip(vals, maxs)]
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
):
    score     = analysis.get("investment_score", 0)
    breakdown = analysis.get("score_breakdown", {})
    is_cash   = fin.get("is_cash", False)

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
            diff      = fin["monthly_gross_income"] - rent_zest
            diff_pct  = diff / rent_zest * 100
            b4.metric(
                "Zillow推定賃料との差",
                f"${diff:+,.0f}/月",
                f"Zestimate: ${rent_zest:,.0f}/月 ({diff_pct:+.1f}%)",
            )
        else:
            b4.metric("Zillow Rent Zestimate", "データなし", "")

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
        prop_rows = []
        if not prop.get("error"):
            prop_rows = [
                ("物件タイプ",       prop.get("homeType", "不明")),
                ("広さ",             f"{prop.get('livingArea','N/A')} sq ft" if prop.get("livingArea") else "N/A"),
                ("土地面積",         f"{prop.get('lotAreaValue','N/A')} sq ft" if prop.get("lotAreaValue") else "N/A"),
                ("寝室/浴室",        f"{prop.get('bedrooms','N/A')}床 / {prop.get('bathrooms','N/A')}浴"),
                ("築年",             f"{prop.get('yearBuilt','N/A')}年" if prop.get("yearBuilt") else "N/A"),
                ("Zestimate",        usd(prop.get("zestimate", 0)) if prop.get("zestimate") else "N/A"),
                ("Rent Zestimate",   f"{usd(prop.get('rentZestimate',0))}/月" if prop.get("rentZestimate") else "N/A"),
                ("最終売却",         f"{usd(prop.get('lastSoldPrice',0))} ({prop.get('lastSoldDate','')})"
                                     if prop.get("lastSoldPrice") else "N/A"),
            ]
            # 賃料市場比較
            if prop.get("rentZestimate") and fin.get("monthly_gross_income"):
                rz        = prop["rentZestimate"]
                ur        = fin["monthly_gross_income"]
                diff_pct  = (ur - rz) / rz * 100
                marker    = "⬆️ 相場より高め" if diff_pct > 5 else "⬇️ 相場より低め" if diff_pct < -5 else "≈ 相場並み"
                prop_rows.append(("賃料市場比較", f"{marker} ({diff_pct:+.1f}%)"))
        html = '<div class="card"><h4>🏠 物件情報</h4>'
        if prop_rows:
            for label, val in prop_rows:
                if val != "N/A":
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

    # ── Location ──────────────────────────────────────────────────────────────
    st.markdown('<div class="section-title">📍 周辺環境・安全性</div>', unsafe_allow_html=True)

    if not loc.get("error"):
        la, lb, lc = st.columns(3)

        # 学校: Zillow データ優先（評価スコア付き）、なければ Google Maps
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
                name    = s.get("name", "")
                rating  = s.get("rating", "")
                dist    = s.get("distance", "")
                level   = s.get("level", "")
                parts   = []
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

        # 犯罪データ表示
        crime = loc.get("crime", {})
        if crime and not crime.get("error"):
            safety_score    = crime.get("safety_score", 0)
            safety_label    = crime.get("safety_label", "")
            total_incidents = crime.get("total_incidents", 0)
            year            = crime.get("year", "")
            top_crimes      = crime.get("top_crime_types", [])
            radius_m        = crime.get("radius_meters", 800)

            if safety_score >= 70:
                c_color, c_bg, c_icon = "#2e7d32", "#e8f5e9", "✅"
            elif safety_score >= 40:
                c_color, c_bg, c_icon = "#e65100", "#fff3e0", "⚠️"
            else:
                c_color, c_bg, c_icon = "#b71c1c", "#ffebee", "🚨"

            crimes_str = (" / ".join(f"{c['type']}({c['count']}件)" for c in top_crimes[:4])
                          if top_crimes else "データなし")
            st.markdown(f"""
            <div style="background:{c_bg};border-left:4px solid {c_color};border-radius:8px;
                        padding:1rem 1.2rem;margin-top:1rem">
                <div style="font-weight:700;color:{c_color};font-size:1rem">
                    {c_icon} 安全スコア: {safety_score}/100 ― {safety_label}
                </div>
                <div style="color:#555;font-size:.88rem;margin-top:.4rem">
                    {year}年 半径{radius_m}m以内の犯罪件数:
                    <strong>{total_incidents}件</strong>（出典: Chicago Data Portal）
                </div>
                <div style="color:#555;font-size:.85rem;margin-top:.3rem">
                    主な犯罪タイプ: {crimes_str}
                </div>
            </div>
            """, unsafe_allow_html=True)
        elif crime.get("error") and "未対応" not in crime.get("error", ""):
            st.info(f"⚠️ 犯罪データ: {crime['error']}")

        road = loc.get("road_info", {})
        if road.get("road_name") and road["road_name"] != "不明":
            if road.get("is_major_road"):
                st.warning(f"⚠️ **道路情報**: 主要道路沿い（{road['road_name']}）― 騒音・安全性に注意")
            else:
                st.success(f"✅ **道路情報**: 住宅街区内の静かな道路（{road['road_name']}）")
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
    sim = calc_10year_simulation(fin, rent_growth, appreciation)
    st.plotly_chart(ten_year_chart(sim), use_container_width=True)

    sim_df = pd.DataFrame(sim).copy()
    for col in ["物件価値", "月額賃料", "年間NOI", "年間CF", "累積CF", "ローン残高", "エクイティ", "総リターン"]:
        sim_df[col] = sim_df[col].apply(lambda x: f"${x:,.0f}")
    st.dataframe(sim_df, use_container_width=True, hide_index=True)

    # ── Depreciation ──────────────────────────────────────────────────────────
    st.markdown('<div class="section-title">🏛️ 減価償却・節税効果（日本人投資家向け）</div>', unsafe_allow_html=True)
    depr = calc_depreciation(fin["purchase_price"], land_pct)
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
        <p style="font-size:.82rem;opacity:.7;margin-top:.4rem">Powered by Claude AI · Google Maps · Zillow</p>
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
        st.markdown("""
**📊 指標の目安**
| 指標 | 優良 | 標準 | 要注意 |
|---|---|---|---|
| Cap Rate | ≥6% | 4-6% | <4% |
| CoC Return | ≥8% | 4-8% | <4% |
| GRM | <12× | 12-18× | >18× |
| 投資スコア | ≥80 | 50-79 | <50 |
        """)
        st.divider()
        st.markdown("**🔑 API 設定確認**")
        st.markdown(f"Zillow (RapidAPI): {'✅' if os.getenv('RAPIDAPI_KEY') else '❌ 未設定'}")
        st.markdown(f"Google Maps:       {'✅' if os.getenv('GOOGLE_MAPS_API_KEY') else '❌ 未設定'}")
        st.markdown(f"Anthropic Claude:  {'✅' if os.getenv('ANTHROPIC_API_KEY') else '❌ 未設定'}")

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

    # 購入方法はフォームの外に置いて動的切り替えを実現
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
            # キャッシュ購入：賃料・HOAのみ
            st.markdown("#### 💵 キャッシュ購入 ― 収益条件")
            cc1, cc2 = st.columns(2)
            with cc1: monthly_rent = st.number_input("予想月額賃料 ($)", 500, 30_000, 2_400, 50)
            with cc2: hoa          = st.number_input("HOA/管理費 ($/月)", 0, 3_000, 0, 25)
            # ローン不要
            down_pct = 100
            rate     = 0.0
            term     = 30
        else:
            # ローン購入：全項目
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
        progress.progress(30)

        status.markdown("📍 **Google Mapsで周辺環境を分析中…**")
        loc_data = fetcher.get_all_location_data(address)
        progress.progress(60)

        status.markdown("🤖 **Claude AIが投資分析を実行中…**")
        analysis = analyzer.analyze_property(prop_data, loc_data, fin)
        progress.progress(100)

        status.empty()
        progress.empty()

        if analysis.get("error") and not analysis.get("investment_score"):
            st.error(f"AI分析エラー: {analysis['error']}")
            return

        st.success(f"✅ 分析完了: **{address}**")
        show_results(analysis, prop_data, loc_data, fin, usd_to_jpy,
                     rent_growth, appreciation, land_pct)

        # ── Add to comparison list ─────────────────────────────────────────
        st.divider()
        if st.button("📊 この物件を比較リストに追加", key="add_comp", use_container_width=False):
            entry = {
                "住所":    address[:45] + ("…" if len(address) > 45 else ""),
                "スコア":  analysis.get("investment_score", 0),
                "Cap Rate": f"{fin['cap_rate']:.2f}%",
                "CoC":     f"{fin['coc_return']:.2f}%",
                "月次CF":  f"${fin['monthly_cash_flow']:,.0f}",
                "購入価格": f"${fin['purchase_price']:,.0f}",
                "推奨":    analysis.get("recommendation", ""),
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
