import os
import json
import re
import anthropic


SYSTEM_PROMPT = """あなたは日本人投資家向けのアメリカ不動産投資の専門AIコンサルタントです。
豊富な市場知識と財務分析の専門性を持ち、客観的で実用的な投資アドバイスを日本語で提供します。
分析は必ずJSON形式で返してください。"""


class PropertyAnalyzer:
    """Claude を使った不動産投資分析エンジン"""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

    def analyze_property(
        self,
        property_data: dict,
        location_data: dict,
        financials: dict,
        market_data: dict = None,
    ) -> dict:
        """全データを統合して投資分析を実行"""
        prompt = self._build_prompt(property_data, location_data, financials, market_data or {})
        try:
            message = self.client.messages.create(
                model="claude-haiku-4-5-20251001",  # 最安モデル。Sonnetに変えると高品質
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text
            return self._parse_json(raw)
        except Exception as e:
            return {"error": str(e), "investment_score": 0}

    # ──────────────────────────────────────────────────────────────────────────
    # Prompt construction
    # ──────────────────────────────────────────────────────────────────────────

    def _build_prompt(self, prop: dict, loc: dict, fin: dict, mkt: dict = None) -> str:
        prop_section = self._fmt_property(prop)
        loc_section = self._fmt_location(loc)
        fin_section = self._fmt_financials(fin)
        mkt_section = self._fmt_market(mkt or {})

        return f"""以下のアメリカ不動産物件を日本人投資家の視点から詳細に分析してください。

━━━ 物件情報 ━━━
{prop_section}

━━━ 財務指標 ━━━
{fin_section}

━━━ 周辺環境 ━━━
{loc_section}

━━━ マーケットデータ ━━━
{mkt_section}

━━━ 出力形式 ━━━
以下のJSONのみを返してください（余分なテキスト不要）:

{{
  "investment_score": <0〜100の整数>,
  "score_breakdown": {{
    "location_score": <0〜30>,
    "location_max": 30,
    "financial_score": <0〜40>,
    "financial_max": 40,
    "property_score": <0〜20>,
    "property_max": 20,
    "market_score": <0〜10>,
    "market_max": 10
  }},
  "recommendation": "<長期保有推奨 or 早期売却推奨 or 条件付き推奨 など>",
  "hold_years": "<推奨保有期間。例: 5〜10年>",
  "strengths": ["<強み1>", "<強み2>", "<強み3>"],
  "risks": ["<リスク1>", "<リスク2>", "<リスク3>"],
  "financial_analysis": "<財務分析（キャップレート・CF・CoC・GRM・価格妥当性について300字以上）>",
  "location_analysis": "<立地分析（学校区・生活利便性・主要道路・交通アクセスについて200字以上）>",
  "market_outlook": "<市場見通し（エリアの成長性・賃貸需要・価格トレンドについて200字以上）>",
  "overall_comment": "<総合評価（投資家への具体的アドバイスを含む300字以上）>",
  "action_plan": "<推奨アクション（価格交渉・ローン戦略・管理方針など具体的に200字以上）>",
  "tax_considerations": "<日本人投資家向け税務上の注意点（FIRPTA・確定申告・日米租税条約など200字以上）>"
}}

【採点基準】
- 立地スコア（30点）: 学校区の質(7点)、生活利便性(7点)、交通アクセス(6点)、静閑性・主要道路(5点)、安全性・犯罪率(5点)
- 財務スコア（40点）: キャップレート(10点)、CoC・CF(10点)、価格妥当性・GRM(10点)、賃料/価格比(10点)
- 物件スコア（20点）: 築年数・状態(8点)、広さ・間取り(7点)、物件タイプ(5点)
- 市場スコア（10点）: エリア成長性(5点)、賃貸需要・流動性(5点)

【重要な分析指針】
1. 郡・エリア成長性の評価: 市単体の人口規模ではなく、郡レベルの人口増加率を重視してください。郊外の新興住宅地（例: テキサス北部の急成長郡内の小都市）は、市の絶対人口は小さくても郡全体の成長需要を受益します。郡の2年間成長率が+3%以上なら「成長エリア」として評価してください。
2. 運営経費率の評価: 入力された経費率（例: 40%）は業界標準の「50%ルール」から導かれた保守的な見積もりです。単家族住宅の実績値は通常35〜45%の範囲であり、40%は妥当な前提です。「根拠不明確」とは評価しないでください。
3. GRMの評価基準（Gross Rent Multiplier）: テキサス州DFW市場の単家族住宅における典型的なGRM相場は10〜14倍です（全米平均は12〜18倍）。GRMが低いほど賃料対価格比が優れているため、GRM10〜12倍はDFW市場では「良好」な投資効率です。比較対象がないとは評価しないでください。
4. 複数ソース価格比較: Zillow・Redfin・Realtor.com・Collin CAD評価額が提供されている場合は、それらを比較して購入価格の妥当性を多角的に評価してください。
5. 賃貸需要・空室率の評価: Census ACS空室率データやFREDの賃貸空室率データが提供されている場合、それを根拠として賃貸需要を具体的に評価してください。テキサス州の賃貸空室率データが示す通り、エリアの具体的な数値を使用してください。
"""

    def _fmt_property(self, prop: dict) -> str:
        if prop.get("error"):
            return f"取得失敗: {prop['error']}"

        lines = []
        fields = [
            ("住所", prop.get("streetAddress", prop.get("address", "不明"))),
            ("市区", f"{prop.get('city', '')} {prop.get('state', '')} {prop.get('zipcode', '')}"),
            ("物件タイプ", prop.get("homeType", "不明")),
            ("広さ", f"{prop.get('livingArea', 'N/A')} sq ft" if prop.get("livingArea") else "N/A"),
            ("土地面積", f"{prop.get('lotAreaValue', 'N/A')} {prop.get('lotAreaUnit', 'sqft')}" if prop.get("lotAreaValue") else "N/A"),
            ("寝室", prop.get("bedrooms", "N/A")),
            ("浴室", prop.get("bathrooms", "N/A")),
            ("築年", prop.get("yearBuilt", "N/A")),
            ("Zestimate（推定価格）", f"${prop.get('zestimate', 0):,.0f}" if prop.get("zestimate") else "N/A"),
            ("Rent Zestimate（推定賃料）", f"${prop.get('rentZestimate', 0):,.0f}/月" if prop.get("rentZestimate") else "N/A"),
            ("最終売却価格", f"${prop.get('lastSoldPrice', 0):,.0f}" if prop.get("lastSoldPrice") else "N/A"),
            ("最終売却日", prop.get("lastSoldDate", "N/A")),
            ("物件説明", (prop.get("description", "") or "")[:300]),
        ]
        for label, value in fields:
            if value and value != "N/A":
                lines.append(f"- {label}: {value}")

        price_history = prop.get("priceHistory", [])
        if price_history:
            lines.append("\n【取引・価格履歴】")
            for event in price_history[:6]:
                date = event.get("date", "")
                etype = event.get("event", "")
                price = event.get("price", 0)
                if price:
                    lines.append(f"  {date} | {etype} | ${price:,.0f}")

        schools = prop.get("schools", [])
        if schools:
            lines.append("\n【Zillow学区情報】")
            for s in schools[:3]:
                name = s.get("name", "")
                rating = s.get("rating", "")
                dist = s.get("distance", "")
                lines.append(f"  {name} (評価: {rating}/10, {dist}マイル)")

        violations = prop.get("violations", prop.get("openCodeViolations", []))
        if violations:
            lines.append(f"\n【バイオレーション】{len(violations)}件")
        else:
            lines.append("\n【バイオレーション】記録なし（Zillowデータ範囲内）")

        return "\n".join(lines)

    def _fmt_financials(self, fin: dict) -> str:
        is_cash = fin.get("is_cash", False)
        lines = [
            f"- 購入方法: {'全キャッシュ（ローンなし）' if is_cash else 'ローン（モーゲージ）'}",
            f"- 購入価格: ${fin['purchase_price']:,.0f}",
        ]
        if is_cash:
            lines += [
                f"- 諸費用: ${fin['closing_costs']:,.0f}",
                f"- 必要現金合計（全額キャッシュ）: ${fin['total_cash_needed']:,.0f}",
                f"- ローン: なし",
                f"- 月次モーゲージ: $0",
            ]
        else:
            lines += [
                f"- 頭金: ${fin['down_payment']:,.0f} ({fin['down_payment_pct']:.0f}%)",
                f"- 諸費用: ${fin['closing_costs']:,.0f}",
                f"- 必要現金合計: ${fin['total_cash_needed']:,.0f}",
                f"- ローン額: ${fin['loan_amount']:,.0f}",
                f"- 金利: {fin['mortgage_rate']:.3f}% / {fin['loan_term_years']}年固定",
                f"- 月次モーゲージ: ${fin['monthly_mortgage']:,.0f}",
            ]
        lines += [
            f"- 予想月額賃料: ${fin['monthly_gross_income']:,.0f}",
            f"- 月次運営経費 ({fin.get('expense_ratio', 40):.0f}%): ${fin['monthly_expenses']:,.0f}",
        ]
        if fin.get("monthly_hoa", 0) > 0:
            lines.append(f"- HOA/管理費: ${fin['monthly_hoa']:,.0f}/月")
        lines += [
            f"- 月次NOI: ${fin['monthly_noi']:,.0f}",
            f"- 年間NOI: ${fin['annual_noi']:,.0f}",
            f"- 月次キャッシュフロー: ${fin['monthly_cash_flow']:,.0f}",
            f"- 年間キャッシュフロー: ${fin['annual_cash_flow']:,.0f}",
            f"- キャップレート: {fin['cap_rate']:.2f}%",
            f"- Cash-on-Cash リターン: {fin['coc_return']:.2f}%",
            f"- GRM（賃料乗数）: {fin['grm']:.1f}倍",
            f"- 賃料/価格比: {fin['rent_to_price']:.3f}%",
        ]
        return "\n".join(lines)

    def _fmt_market(self, mkt: dict) -> str:
        if not mkt:
            return "市場データなし"
        lines = []
        # 住宅ローン金利
        rates = mkt.get("mortgage_rates", {})
        if not rates.get("error"):
            for sid, info in rates.items():
                if isinstance(info, dict) and "latest" in info:
                    lines.append(f"- {info['label']}金利（FRED）: {info['latest']:.3f}%")
        # 賃貸空室率
        vacancy = mkt.get("rental_vacancy", {})
        if not vacancy.get("error"):
            for sid, info in vacancy.items():
                if isinstance(info, dict) and "latest" in info:
                    v = info["latest"]
                    v_label = "低空室（需要旺盛）" if v < 6 else "標準的水準" if v < 10 else "高空室（供給過剰気味）"
                    lines.append(f"- {info['label']}（FRED {info.get('date','')}）: {v:.1f}% ― {v_label}")
        return "\n".join(lines) if lines else "市場データなし"

    def _fmt_location(self, loc: dict) -> str:
        if loc.get("error"):
            return f"取得失敗: {loc['error']}"

        lines = []
        geo = loc.get("geocode", {})
        if geo.get("formatted_address"):
            lines.append(f"- 正式住所: {geo['formatted_address']}")

        def fmt_places(label, items, max_count=4):
            if not items:
                return f"- {label}: データなし"
            parts = [f"{p['name']}({p['distance_miles']}マイル)" for p in items[:max_count]]
            return f"- {label}: {', '.join(parts)}"

        lines.append(fmt_places("学校", loc.get("schools", [])))
        lines.append(fmt_places("スーパー/食料品店", loc.get("supermarkets", [])))
        lines.append(fmt_places("ショッピング", loc.get("shopping", [])))
        lines.append(fmt_places("レストラン", loc.get("restaurants", [])))
        lines.append(fmt_places("交通機関（Google Maps）", loc.get("transit", [])))

        # SchoolDigger 学校評価
        sd_schools = loc.get("school_ratings", [])
        if sd_schools:
            lines.append("\n【SchoolDigger 学校評価・ランキング】")
            for s in sd_schools[:4]:
                stars_str = f"{s['rating']:.1f}/5" if s.get("rating") is not None else "評価なし"
                rank_str  = f"州内{s['rank']:,}位/{s['rank_of']:,}校" if s.get("rank") and s.get("rank_of") else ""
                lines.append(f"  - {s['name']}（{s.get('grades','')}）: ⭐{stars_str} {rank_str}")

        # 交通機関詳細（OpenStreetMap）
        transit_det = loc.get("transit_detailed", {})
        if transit_det and not transit_det.get("error"):
            if transit_det.get("car_dependent"):
                lines.append(f"- 交通機関（OpenStreetMap）: 半径{transit_det.get('radius_miles',1.9)}マイル以内に公共交通機関なし → 完全自動車依存エリア")
            else:
                stops = transit_det.get("stops", [])
                stop_str = ", ".join(f"{s['type']}{s['name']}({s['distance_miles']}マイル)" for s in stops[:3])
                lines.append(f"- 交通機関（OpenStreetMap）: {stop_str}")

        road = loc.get("road_info", {})
        if road.get("road_name"):
            road_label = "主要道路沿い" if road.get("is_major_road") else "住宅街区内"
            lines.append(f"- 道路状況: {road_label}（{road['road_name']}）")

        crime = loc.get("crime", {})
        if crime and not crime.get("error"):
            safety = crime.get("safety_score", 0)
            label  = crime.get("safety_label", "")
            total  = crime.get("total_incidents", 0)
            year   = crime.get("year", "")
            top    = crime.get("top_crime_types", [])
            lines.append(f"- 安全スコア: {safety}/100 ({label}) ― {year}年 半径800m以内: {total}件")
            if top:
                top_str = "、".join(f"{t['type']}({t['count']}件)" for t in top[:3])
                lines.append(f"- 主要犯罪タイプ: {top_str}")
        elif crime.get("error"):
            lines.append(f"- 犯罪データ: {crime['error']}")

        # Walk Score
        walk = loc.get("walk_score", {})
        if walk and not walk.get("error"):
            ws = walk.get("walk_score", 0)
            ts = walk.get("transit_score", "N/A")
            bs = walk.get("bike_score", "N/A")
            lines.append(f"- Walk Score: {ws}/100 ({walk.get('walk_desc','')}) / Transit: {ts} / Bike: {bs}")

        # Flood zone
        flood = loc.get("flood_zone", {})
        if flood and not flood.get("error"):
            lines.append(f"- 洪水ゾーン: {flood.get('zone','X')} ― {flood.get('description','')} (保険必須: {'はい' if flood.get('insurance_required') else 'いいえ'})")

        # Census demographics
        demo = loc.get("demographics", {})
        if demo and not demo.get("error"):
            lines.append(f"- 世帯中央所得: ${demo.get('median_income', 0):,}/年")
            lines.append(f"- 総人口: {demo.get('total_population', 0):,}人")
            lines.append(f"- 空室率: {demo.get('vacancy_rate', 0):.1f}% / 借家比率: {demo.get('renter_pct', 0):.1f}%")

        # County population growth
        pg = loc.get("population_growth", {})
        if pg and not pg.get("error"):
            g2 = pg.get("growth_2yr_pct", 0)
            trend = "急成長エリア" if g2 >= 5 else "成長中" if g2 >= 3 else "緩成長" if g2 >= 0 else "人口減少"
            lines.append(f"- 郡人口増加率（2020→2022）: {g2:+.1f}% ― {trend} ({pg.get('county_name','')})")
            lines.append(f"- 2022年郡人口: {pg.get('pop_2022',0):,}人 / 人口密度: {pg.get('density',0):.1f}人/sq mi")

        # BLS unemployment
        unemp = loc.get("unemployment", {})
        if unemp and not unemp.get("error"):
            lines.append(f"- 州失業率: {unemp.get('unemployment_rate', 0):.1f}% ({unemp.get('period', '')})")

        # HUD Fair Market Rent
        hud = loc.get("hud_fmr", {})
        if hud and not hud.get("error"):
            lines.append(f"- HUD公正市場賃料 ({hud.get('area_name', '')}): 1BR=${hud.get('1br', 0):,} / 2BR=${hud.get('2br', 0):,} / 3BR=${hud.get('3br', 0):,}")

        # Collin CAD 固定資産評価データ（Texas Open Data Portal）
        ccad = loc.get("ccad", {})
        if ccad and not ccad.get("error"):
            lines.append("\n【Collin CAD 固定資産評価データ（Texas Open Data Portal）】")
            if ccad.get("year_built"):
                lines.append(f"  - 築年（公的記録）: {ccad['year_built']}年")
            if ccad.get("sqft"):
                lines.append(f"  - 建物面積（公的記録）: {ccad['sqft']:,} sq ft")
            if ccad.get("market_value"):
                lines.append(f"  - CAD市場評価額: ${ccad['market_value']:,}")
            if ccad.get("imprv_value") and ccad.get("land_value"):
                lines.append(f"  - 建物価値: ${ccad['imprv_value']:,} ／ 土地価値: ${ccad['land_value']:,}")
            if ccad.get("land_pct"):
                lines.append(f"  - 土地割合: {ccad['land_pct']}%（減価償却計算の参考値）")
            if ccad.get("pool"):
                lines.append(f"  - プール: あり")
            if ccad.get("prev_market_value") and ccad.get("market_value"):
                chg = ccad["market_value"] - ccad["prev_market_value"]
                chg_pct = chg / ccad["prev_market_value"] * 100 if ccad["prev_market_value"] > 0 else 0
                lines.append(f"  - 前年比価値変動: {chg:+,}（{chg_pct:+.1f}%）")
            if ccad.get("deed_date"):
                lines.append(f"  - 直近売買日（証書）: {ccad['deed_date']}")

        # Redfin価格情報
        redfin = loc.get("redfin", {})
        if redfin and not redfin.get("error"):
            lp   = redfin.get("list_price")
            est  = redfin.get("estimate")
            dom  = redfin.get("days_on_market")
            ppsf = redfin.get("price_per_sqft")
            price_str = (f"${lp:,}" if lp else (f"推定${est:,}" if est else "N/A"))
            dom_str   = f"{dom}日" if dom is not None else "N/A"
            ppsf_str  = f"${ppsf:,}/sqft" if ppsf else "N/A"
            lines.append(f"- Redfin価格情報: {price_str} / $/sqft: {ppsf_str} / 市場掲載日数: {dom_str} / ステータス: {redfin.get('status','N/A')}")

        # Realtor.com価格情報
        realtor = loc.get("realtor", {})
        if realtor and not realtor.get("error"):
            lp   = realtor.get("list_price")
            est  = realtor.get("estimate")
            dom  = realtor.get("days_on_market")
            ppsf = realtor.get("price_per_sqft")
            price_str = (f"${lp:,}" if lp else (f"推定${est:,}" if est else "N/A"))
            dom_str   = f"{dom}日" if dom is not None else "N/A"
            ppsf_str  = f"${ppsf:,}/sqft" if ppsf else "N/A"
            lines.append(f"- Realtor.com価格情報: {price_str} / $/sqft: {ppsf_str} / 市場掲載日数: {dom_str} / ステータス: {realtor.get('status','N/A')}")

        return "\n".join(lines)

    @staticmethod
    def _parse_json(text: str) -> dict:
        """Claude レスポンスから JSON を抽出"""
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{[\s\S]+\}", text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return {"error": "JSON解析失敗", "raw": text[:500], "investment_score": 0}
