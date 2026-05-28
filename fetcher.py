import os
import math
import datetime
import requests
from collections import Counter
from typing import Optional


# ──────────────────────────────────────────────────────────────────────────────
# Module-level constants
# ──────────────────────────────────────────────────────────────────────────────

STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08",
    "CT": "09", "DE": "10", "FL": "12", "GA": "13", "HI": "15", "ID": "16",
    "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21", "LA": "22",
    "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27", "MS": "28",
    "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33", "NJ": "34",
    "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39", "OK": "40",
    "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46", "TN": "47",
    "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53", "WV": "54",
    "WI": "55", "WY": "56", "DC": "11",
}

FLOOD_ZONE_INFO = {
    "A":  {"risk": "高",   "sfha": True,  "color": "#b71c1c", "label": "100年洪水ゾーン（保険必須）"},
    "AE": {"risk": "高",   "sfha": True,  "color": "#b71c1c", "label": "100年洪水ゾーン・BFE設定済（保険必須）"},
    "AO": {"risk": "高",   "sfha": True,  "color": "#b71c1c", "label": "河川型浅水洪水（保険必須）"},
    "AH": {"risk": "高",   "sfha": True,  "color": "#b71c1c", "label": "浅水洪水（保険必須）"},
    "V":  {"risk": "最高", "sfha": True,  "color": "#7f0000", "label": "沿岸高波ゾーン（保険必須）"},
    "VE": {"risk": "最高", "sfha": True,  "color": "#7f0000", "label": "沿岸高波・BFE設定済（保険必須）"},
    "X":  {"risk": "低",   "sfha": False, "color": "#2e7d32", "label": "低リスクゾーン（保険任意）"},
    "D":  {"risk": "不明", "sfha": False, "color": "#f57f17", "label": "未判定ゾーン"},
}


class PropertyDataFetcher:
    """Zillow API + Google Maps API + 各種無料/有料APIからデータ取得"""

    ZILLOW_HOST    = "real-estate-zillow-com.p.rapidapi.com"
    MAPS_BASE      = "https://maps.googleapis.com/maps/api"
    FRED_BASE      = "https://api.stlouisfed.org/fred"
    FEMA_FLOOD_URL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
    CENSUS_BASE    = "https://api.census.gov/data"
    CENSUS_GEOCODER = "https://geocoding.geo.census.gov/geocoder/geographies/address"
    BLS_URL        = "https://api.bls.gov/publicAPI/v1/timeseries/data"
    HUD_BASE       = "https://www.huduser.gov/hudapi/public"
    WALKSCORE_URL  = "https://api.walkscore.com/score"
    FBI_BASE       = "https://api.usa.gov/crime/fbi/sapi"

    def __init__(self):
        self.rapidapi_key  = os.getenv("RAPIDAPI_KEY", "")
        self.google_key    = os.getenv("GOOGLE_MAPS_API_KEY", "")
        self.fred_key      = os.getenv("FRED_API_KEY", "")
        self.census_key    = os.getenv("CENSUS_API_KEY", "")
        self.hud_token     = os.getenv("HUD_API_TOKEN", "")
        self.walkscore_key = os.getenv("WALKSCORE_API_KEY", "")
        self.fbi_key       = os.getenv("FBI_API_KEY", "")

    # ──────────────────────────────────────────────────────────────────────────
    # Zillow
    # ──────────────────────────────────────────────────────────────────────────

    def get_property_data(self, address: str) -> dict:
        """住所から Zillow 物件データを取得"""
        if not self.rapidapi_key:
            return {"error": "RAPIDAPI_KEY が設定されていません"}

        zpid = self._search_zpid(address)
        if not zpid:
            return {"error": "物件が見つかりませんでした", "address": address}

        details = self._get_property_details(zpid)
        return details

    def _search_zpid(self, address: str) -> Optional[str]:
        """住所から zpid を取得"""
        url = f"https://{self.ZILLOW_HOST}/v1/search/sale"
        headers = {
            "X-RapidAPI-Key":  self.rapidapi_key,
            "X-RapidAPI-Host": self.ZILLOW_HOST,
        }
        try:
            resp = requests.get(
                url,
                headers=headers,
                params={"location": address, "limit": "1"},
                timeout=15,
            )
            data = resp.json()
            results = data.get("results", data.get("props", []))
            if results:
                item = results[0]
                return str(item.get("zpid", item.get("id", "")))
        except Exception:
            pass
        return None

    def _get_property_details(self, zpid: str) -> dict:
        """zpid から物件詳細を取得"""
        url = f"https://{self.ZILLOW_HOST}/v1/property"
        headers = {
            "X-RapidAPI-Key":  self.rapidapi_key,
            "X-RapidAPI-Host": self.ZILLOW_HOST,
        }
        try:
            resp = requests.get(url, headers=headers, params={"zpid_or_url": zpid}, timeout=15)
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

    # ──────────────────────────────────────────────────────────────────────────
    # Google Maps
    # ──────────────────────────────────────────────────────────────────────────

    def get_all_location_data(self, address: str) -> dict:
        """住所から周辺環境データをすべて取得"""
        if not self.google_key:
            return {"error": "GOOGLE_MAPS_API_KEY が設定されていません"}

        geocode = self._geocode(address)
        if not geocode:
            return {"error": "住所のジオコーディングに失敗しました"}

        lat, lng = geocode["lat"], geocode["lng"]

        # 住所コンポーネントから市・州・郵便番号を抽出
        city = state = zipcode = ""
        for comp in geocode.get("components", []):
            types = comp.get("types", [])
            if "locality" in types:
                city = comp.get("long_name", "")
            if "administrative_area_level_1" in types:
                state = comp.get("short_name", "")
            if "postal_code" in types:
                zipcode = comp.get("long_name", "")

        return {
            "geocode":      geocode,
            "city":         city,
            "state":        state,
            "zipcode":      zipcode,
            "schools":      self._nearby_places(lat, lng, "school",                  radius=2400),
            "supermarkets": self._nearby_places(lat, lng, "grocery_or_supermarket",  radius=2400),
            "shopping":     self._nearby_places(lat, lng, "shopping_mall",           radius=3200),
            "restaurants":  self._nearby_places(lat, lng, "restaurant",              radius=1600),
            "transit":      self._nearby_places(lat, lng, "transit_station",         radius=1600),
            "road_info":    self._check_road(lat, lng),
            "crime":        self.get_crime_data(lat, lng, city, state),
            "walk_score":   self.get_walk_score(lat, lng, address),
            "flood_zone":   self.get_fema_flood_zone(lat, lng),
            "demographics":      self.get_census_demographics(zipcode),
            "population_growth": self.get_county_population_growth(address, state) if state else {"error": "州不明"},
            "unemployment":      self.get_bls_unemployment(state) if state else {"error": "州不明"},
            "hud_fmr":           self.get_hud_fair_market_rent(state, city) if state else {"error": "州不明"},
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Crime data (Chicago Data Portal — free, no key)
    # ──────────────────────────────────────────────────────────────────────────

    def get_crime_data(self, lat: float, lng: float, city: str = "", state: str = "") -> dict:
        """犯罪データを取得（Chicago詳細 / FBI全米対応）"""
        # シカゴは独自のData Portalで半径ベースの詳細データを優先
        if "CHICAGO" in city.upper() or ("IL" in state.upper() and 41.6 < lat < 42.1):
            result = self._get_chicago_crime(lat, lng)
            if not result.get("error"):
                return result
        # FBIデータで全米対応（TX・IL他すべての都市）
        if city and state:
            return self.get_fbi_crime_data(city, state)
        return {"error": "犯罪データ未対応エリア", "safety_score": None}

    def _get_chicago_crime(self, lat: float, lng: float, radius_m: int = 800) -> dict:
        """Chicago Data Portal から過去1年の犯罪データを取得（無料・APIキー不要）"""
        lat_d = radius_m / 111_000
        lng_d = radius_m / (111_000 * math.cos(math.radians(lat)))
        year  = datetime.datetime.now().year - 1
        try:
            resp = requests.get(
                "https://data.cityofchicago.org/resource/ijzp-q8t2.json",
                params={
                    "$where": (
                        f"latitude > '{lat - lat_d:.6f}' AND latitude < '{lat + lat_d:.6f}' "
                        f"AND longitude > '{lng - lng_d:.6f}' AND longitude < '{lng + lng_d:.6f}' "
                        f"AND year = '{year}'"
                    ),
                    "$limit":  500,
                    "$select": "primary_type",
                },
                timeout=15,
            )
            data = resp.json()
            if isinstance(data, list):
                total       = len(data)
                type_counts = Counter(c.get("primary_type", "OTHER") for c in data)
                if   total == 0:   safety = 95
                elif total < 10:   safety = 85
                elif total < 25:   safety = 70
                elif total < 50:   safety = 50
                elif total < 100:  safety = 30
                else:              safety = 15
                return {
                    "source":          "Chicago Data Portal",
                    "year":            year,
                    "radius_meters":   radius_m,
                    "total_incidents": total,
                    "top_crime_types": [{"type": t, "count": c} for t, c in type_counts.most_common(5)],
                    "safety_score":    safety,
                    "safety_label":    "安全" if safety >= 70 else "普通" if safety >= 40 else "要注意",
                }
        except Exception:
            pass
        return {"error": "シカゴ犯罪データ取得失敗", "safety_score": None}

    def get_fbi_crime_data(self, city: str, state: str) -> dict:
        """FBI Crime Data Explorer API から市区レベルの犯罪データを取得（全米対応）"""
        if not self.fbi_key:
            return {"error": "FBI_API_KEY 未設定（api.usa.gov/crime/fbi/sapi/ で無料登録）", "safety_score": None}
        # Step 1: 州の警察機関一覧を取得してcityに一致する機関を探す
        try:
            resp = requests.get(
                f"{self.FBI_BASE}/api/agencies/byStateAbbr/{state.upper()}",
                params={"api_key": self.fbi_key},
                timeout=15,
            )
            agencies = resp.json()
            if not isinstance(agencies, list):
                return {"error": "FBI機関データ取得失敗", "safety_score": None}

            city_clean = city.lower().strip()
            matched = None
            # 完全一致（市警察優先）
            for a in agencies:
                if (a.get("city_name", "").lower().strip() == city_clean
                        and "police" in a.get("agency_type_name", "").lower()):
                    matched = a
                    break
            # 部分一致フォールバック
            if not matched:
                for a in agencies:
                    a_city = a.get("city_name", "").lower().strip()
                    if city_clean in a_city or a_city in city_clean:
                        matched = a
                        break
            if not matched:
                return {"error": f"{city}, {state} の犯罪データなし（小規模都市の可能性）", "safety_score": None}

            ori        = matched.get("ori", "")
            pop_agency = matched.get("population", 0) or 50000
            agency_nm  = matched.get("agency_name", city)
        except Exception as e:
            return {"error": f"FBI機関検索失敗: {str(e)}", "safety_score": None}

        # Step 2: 犯罪統計取得（FBIデータは1〜2年遅れ）
        year = datetime.datetime.now().year - 2
        try:
            resp = requests.get(
                f"{self.FBI_BASE}/api/summarized/agencies/{ori}/offenses/{year}/{year}",
                params={"api_key": self.fbi_key},
                timeout=15,
            )
            items = resp.json()
            if not isinstance(items, list):
                return {"error": "FBI犯罪統計の取得失敗", "safety_score": None}

            VIOLENT  = {"murder", "rape", "robbery", "aggravated-assault"}
            PROPERTY = {"burglary", "larceny", "motor-vehicle-theft", "arson"}

            total_v = total_p = 0
            crime_counts: dict = {}
            for item in items:
                offense = item.get("offense", "")
                count   = int(item.get("actual", 0) or 0)
                crime_counts[offense] = crime_counts.get(offense, 0) + count
                if offense in VIOLENT:  total_v += count
                if offense in PROPERTY: total_p += count

            total  = total_v + total_p
            rate   = total / pop_agency * 1000 if pop_agency > 0 else 0
            safety = (90 if rate < 20 else 75 if rate < 40 else 55 if rate < 60
                      else 40 if rate < 80 else 25 if rate < 100 else 10)
            top5   = sorted(crime_counts.items(), key=lambda x: x[1], reverse=True)[:5]

            return {
                "source":               "FBI Crime Data Explorer",
                "agency_name":          agency_nm,
                "year":                 year,
                "total_incidents":      total,
                "total_violent":        total_v,
                "total_property":       total_p,
                "crime_rate_per_1000":  round(rate, 1),
                "population":           pop_agency,
                "top_crime_types":      [{"type": t, "count": c} for t, c in top5],
                "safety_score":         safety,
                "safety_label":         "安全" if safety >= 70 else "普通" if safety >= 40 else "要注意",
            }
        except Exception as e:
            return {"error": f"FBI犯罪統計取得失敗: {str(e)}", "safety_score": None}

    # ──────────────────────────────────────────────────────────────────────────
    # Walk Score API
    # ──────────────────────────────────────────────────────────────────────────

    def get_walk_score(self, lat: float, lng: float, address: str) -> dict:
        """Walk Score API から徒歩・交通・自転車スコアを取得"""
        if not self.walkscore_key:
            return {"error": "WALKSCORE_API_KEY 未設定（walkscore.com/professional で無料登録）"}
        try:
            resp = requests.get(
                self.WALKSCORE_URL,
                params={
                    "format":   "json",
                    "address":  address,
                    "lat":      lat,
                    "lon":      lng,
                    "wsapikey": self.walkscore_key,
                    "transit":  1,
                    "bike":     1,
                },
                timeout=10,
            )
            data = resp.json()
            return {
                "walk_score":   data.get("walkscore", 0),
                "walk_desc":    data.get("description", ""),
                "transit_score": data.get("transit", {}).get("score"),
                "transit_desc": data.get("transit", {}).get("description", ""),
                "bike_score":   data.get("bike", {}).get("score"),
                "bike_desc":    data.get("bike", {}).get("description", ""),
            }
        except Exception as e:
            return {"error": str(e)}

    # ──────────────────────────────────────────────────────────────────────────
    # FRED API (Federal Reserve) — mortgage rates
    # ──────────────────────────────────────────────────────────────────────────

    def get_fred_mortgage_rates(self) -> dict:
        """FRED API から住宅ローン金利データを取得"""
        if not self.fred_key:
            return {"error": "FRED_API_KEY 未設定（fred.stlouisfed.org で無料登録）"}
        results = {}
        for series_id, label in [("MORTGAGE30US", "30年固定"), ("MORTGAGE15US", "15年固定")]:
            try:
                resp = requests.get(
                    f"{self.FRED_BASE}/series/observations",
                    params={
                        "series_id":  series_id,
                        "api_key":    self.fred_key,
                        "limit":      52,
                        "sort_order": "desc",
                        "file_type":  "json",
                    },
                    timeout=10,
                )
                obs = [o for o in resp.json().get("observations", []) if o.get("value") != "."]
                if obs:
                    history = [
                        (o["date"], float(o["value"]))
                        for o in reversed(obs[:52])
                        if o.get("value") != "."
                    ]
                    results[series_id] = {
                        "label":   label,
                        "latest":  float(obs[0]["value"]),
                        "history": history,
                    }
            except Exception:
                pass
        return results if results else {"error": "FRED データ取得失敗"}

    def get_market_data(self) -> dict:
        """市場データ（モーゲージ金利など）を取得"""
        return {"mortgage_rates": self.get_fred_mortgage_rates()}

    # ──────────────────────────────────────────────────────────────────────────
    # FEMA OpenFEMA — flood zone (free, no key)
    # ──────────────────────────────────────────────────────────────────────────

    def get_fema_flood_zone(self, lat: float, lng: float) -> dict:
        """FEMA National Flood Hazard Layer から洪水ゾーン情報を取得"""
        try:
            resp = requests.get(
                self.FEMA_FLOOD_URL,
                params={
                    "geometry":      f"{lng},{lat}",
                    "geometryType":  "esriGeometryPoint",
                    "spatialRel":    "esriSpatialRelIntersects",
                    "outFields":     "FLD_ZONE,ZONE_SUBTY,SFHA_TF",
                    "returnGeometry": "false",
                    "f":             "json",
                },
                timeout=15,
            )
            features = resp.json().get("features", [])
            if features:
                attrs = features[0].get("attributes", {})
                zone  = attrs.get("FLD_ZONE", "X")
                sfha  = attrs.get("SFHA_TF") == "T"
                info  = FLOOD_ZONE_INFO.get(
                    zone,
                    {"risk": "中", "sfha": sfha, "color": "#f57f17", "label": f"ゾーン {zone}"},
                )
                return {
                    "zone":               zone,
                    "zone_subtype":       attrs.get("ZONE_SUBTY", ""),
                    "sfha":               sfha,
                    "insurance_required": sfha,
                    "risk_level":         info["risk"],
                    "color":              info["color"],
                    "description":        info["label"],
                    "source":             "FEMA National Flood Hazard Layer",
                }
            return {
                "zone": "X", "sfha": False, "insurance_required": False,
                "risk_level": "低", "color": "#2e7d32",
                "description": "低リスクゾーン（データなし）", "source": "FEMA NFHL",
            }
        except Exception as e:
            return {"error": f"FEMA データ取得失敗: {str(e)}"}

    # ──────────────────────────────────────────────────────────────────────────
    # US Census ACS 5-Year API
    # ──────────────────────────────────────────────────────────────────────────

    def get_county_population_growth(self, address: str, state: str) -> dict:
        """Census Geocoder（無料） + Census PEP APIで郡レベルの人口増加データを取得"""
        # Step 1: Census Geocoderで住所→郡FIPSコードを取得（キー不要）
        try:
            parts  = [p.strip() for p in address.split(",")]
            street = parts[0] if len(parts) > 0 else address
            city   = parts[1] if len(parts) > 1 else ""
            resp   = requests.get(
                "https://geocoding.geo.census.gov/geocoder/geographies/address",
                params={
                    "street":    street,
                    "city":      city,
                    "state":     state,
                    "benchmark": "Public_AR_Census2020",
                    "vintage":   "Census2020_Census2020",
                    "format":    "json",
                },
                timeout=15,
            )
            matches = resp.json().get("result", {}).get("addressMatches", [])
            if not matches:
                return {"error": "郡コードが取得できませんでした"}
            counties = matches[0].get("geographies", {}).get("Counties", [])
            if not counties:
                return {"error": "郡データなし"}
            county_fips = counties[0].get("COUNTY", "")
            state_fips  = counties[0].get("STATE", "")
            county_name = counties[0].get("NAME", "")
            if not county_fips or not state_fips:
                return {"error": "FIPSコード取得失敗"}
        except Exception as e:
            return {"error": f"Geocoder失敗: {str(e)}"}

        # Step 2: Census PEP APIで人口増加データを取得
        if not self.census_key:
            return {"error": "CENSUS_API_KEY 未設定"}
        try:
            resp = requests.get(
                f"{self.CENSUS_BASE}/2022/pep/population",
                params={
                    "get": "NAME,POP_2022,POP_2021,POP_2020,DENSITY_2022",
                    "for": f"county:{county_fips}",
                    "in":  f"state:{state_fips}",
                    "key": self.census_key,
                },
                timeout=10,
            )
            data = resp.json()
            if len(data) >= 2:
                row      = dict(zip(data[0], data[1]))
                pop_2020 = int(row.get("POP_2020", 0) or 0)
                pop_2021 = int(row.get("POP_2021", 0) or 0)
                pop_2022 = int(row.get("POP_2022", 0) or 0)
                density  = float(row.get("DENSITY_2022", 0) or 0)
                growth_2yr = round((pop_2022 - pop_2020) / pop_2020 * 100, 1) if pop_2020 > 0 else 0
                growth_1yr = round((pop_2022 - pop_2021) / pop_2021 * 100, 1) if pop_2021 > 0 else 0
                return {
                    "county_name": county_name,
                    "state_fips":  state_fips,
                    "county_fips": county_fips,
                    "pop_2020":    pop_2020,
                    "pop_2021":    pop_2021,
                    "pop_2022":    pop_2022,
                    "growth_2yr_pct": growth_2yr,
                    "growth_1yr_pct": growth_1yr,
                    "density":     round(density, 1),
                    "source":      "US Census Population Estimates 2022",
                }
        except Exception as e:
            return {"error": f"人口推計データ取得失敗: {str(e)}"}
        return {"error": "データなし"}

    def get_census_demographics(self, zipcode: str) -> dict:
        """US Census ACS 5-Year から人口統計・所得・住宅データを取得"""
        if not self.census_key:
            return {"error": "CENSUS_API_KEY 未設定（api.census.gov で無料登録）"}
        if not zipcode:
            return {"error": "郵便番号が取得できませんでした"}
        try:
            resp = requests.get(
                f"{self.CENSUS_BASE}/2022/acs/acs5",
                params={
                    "get": "NAME,B19013_001E,B01003_001E,B25002_001E,B25002_002E,B25002_003E,B25003_002E,B25003_003E",
                    "for": f"zip code tabulation area:{zipcode}",
                    "key": self.census_key,
                },
                timeout=10,
            )
            data = resp.json()
            if len(data) >= 2:
                row     = dict(zip(data[0], data[1]))
                total   = int(row.get("B25002_001E", 0) or 0)
                vacant  = int(row.get("B25002_003E", 0) or 0)
                owner   = int(row.get("B25003_002E", 0) or 0)
                renter  = int(row.get("B25003_003E", 0) or 0)
                return {
                    "zip":                zipcode,
                    "name":               row.get("NAME", ""),
                    "median_income":      int(row.get("B19013_001E", 0) or 0),
                    "total_population":   int(row.get("B01003_001E", 0) or 0),
                    "total_housing_units": total,
                    "vacancy_rate":       round(vacant / total * 100, 1) if total > 0 else 0,
                    "owner_pct":          round(owner / (owner + renter) * 100, 1) if (owner + renter) > 0 else 0,
                    "renter_pct":         round(renter / (owner + renter) * 100, 1) if (owner + renter) > 0 else 0,
                    "source":             "US Census ACS 5-Year 2022",
                }
        except Exception as e:
            return {"error": f"Census データ取得失敗: {str(e)}"}
        return {"error": "データなし"}

    # ──────────────────────────────────────────────────────────────────────────
    # BLS API v1 — state unemployment (free, no key)
    # ──────────────────────────────────────────────────────────────────────────

    def get_bls_unemployment(self, state: str) -> dict:
        """BLS API から州の失業率を取得"""
        fips = STATE_FIPS.get(state.upper(), "")
        if not fips:
            return {"error": f"州コード {state} 不明"}
        series_id = f"LASST{fips}0000000000003"
        try:
            resp = requests.get(
                f"{self.BLS_URL}/{series_id}",
                params={"latest": "true"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            series = resp.json().get("Results", {}).get("series", [{}])[0]
            latest = series.get("data", [{}])[0]
            return {
                "state":             state,
                "unemployment_rate": float(latest.get("value", 0)),
                "period":            latest.get("periodName", "") + " " + latest.get("year", ""),
                "source":            "Bureau of Labor Statistics",
            }
        except Exception as e:
            return {"error": f"BLS データ取得失敗: {str(e)}"}

    # ──────────────────────────────────────────────────────────────────────────
    # HUD Fair Market Rent API
    # ──────────────────────────────────────────────────────────────────────────

    def get_hud_fair_market_rent(self, state: str, city: str = "") -> dict:
        """HUD API から公正市場賃料（FMR）を取得"""
        if not self.hud_token:
            return {"error": "HUD_API_TOKEN 未設定（huduser.gov で無料登録）"}
        try:
            resp = requests.get(
                f"{self.HUD_BASE}/fmr/statedata/{state}",
                headers={"Authorization": f"Bearer {self.hud_token}"},
                timeout=10,
            )
            data  = resp.json()
            areas = (
                data.get("data", {}).get("metroareas", [])
                + data.get("data", {}).get("counties", [])
            )
            match = next(
                (a for a in areas if city.lower() in a.get("areaname", "").lower()),
                None,
            )
            if not match and areas:
                match = areas[0]
            if match:
                bd = match.get("basicdata", {})
                return {
                    "area_name": match.get("areaname", ""),
                    "studio":    bd.get("Efficiency", 0),
                    "1br":       bd.get("One-Bedroom", 0),
                    "2br":       bd.get("Two-Bedroom", 0),
                    "3br":       bd.get("Three-Bedroom", 0),
                    "4br":       bd.get("Four-Bedroom", 0),
                    "year":      data.get("data", {}).get("year", ""),
                    "source":    "HUD Fair Market Rents",
                }
        except Exception as e:
            return {"error": f"HUD データ取得失敗: {str(e)}"}
        return {"error": "HUD データなし"}

    # ──────────────────────────────────────────────────────────────────────────
    # Google Maps private helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _geocode(self, address: str) -> Optional[dict]:
        """住所 → lat/lng"""
        try:
            resp = requests.get(
                f"{self.MAPS_BASE}/geocode/json",
                params={"address": address, "key": self.google_key},
                timeout=10,
            )
            data = resp.json()
            if data.get("results"):
                r   = data["results"][0]
                loc = r["geometry"]["location"]
                return {
                    "lat":               loc["lat"],
                    "lng":               loc["lng"],
                    "formatted_address": r["formatted_address"],
                    "components":        r.get("address_components", []),
                }
        except Exception:
            pass
        return None

    def _nearby_places(self, lat: float, lng: float, place_type: str, radius: int) -> list:
        """指定タイプの近隣施設を最大5件取得"""
        try:
            resp = requests.get(
                f"{self.MAPS_BASE}/place/nearbysearch/json",
                params={
                    "location": f"{lat},{lng}",
                    "radius":   radius,
                    "type":     place_type,
                    "key":      self.google_key,
                },
                timeout=10,
            )
            results = resp.json().get("results", [])[:5]
            places  = []
            for p in results:
                plat    = p["geometry"]["location"]["lat"]
                plng    = p["geometry"]["location"]["lng"]
                dist_km = self._haversine(lat, lng, plat, plng)
                places.append({
                    "name":           p.get("name", ""),
                    "distance_miles": round(dist_km * 0.621371, 2),
                    "distance_km":    round(dist_km, 2),
                    "rating":         p.get("rating"),
                    "vicinity":       p.get("vicinity", ""),
                })
            return sorted(places, key=lambda x: x["distance_miles"])
        except Exception:
            return []

    def _check_road(self, lat: float, lng: float) -> dict:
        """物件が主要道路沿いかどうかを逆ジオコーディングで判定"""
        MAJOR_KEYWORDS = {
            "HWY", "HIGHWAY", "BLVD", "BOULEVARD", "PKWY", "PARKWAY",
            "EXPRESSWAY", "FREEWAY", "INTERSTATE", "TURNPIKE", "ROUTE",
        }
        try:
            resp = requests.get(
                f"{self.MAPS_BASE}/geocode/json",
                params={
                    "latlng":      f"{lat},{lng}",
                    "key":         self.google_key,
                    "result_type": "route",
                },
                timeout=10,
            )
            for result in resp.json().get("results", []):
                for comp in result.get("address_components", []):
                    if "route" in comp.get("types", []):
                        road_name = comp.get("long_name", "")
                        is_major  = any(kw in road_name.upper() for kw in MAJOR_KEYWORDS)
                        return {"road_name": road_name, "is_major_road": is_major}
        except Exception:
            pass
        return {"road_name": "不明", "is_major_road": False}

    @staticmethod
    def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """2点間の距離(km)をHaversine公式で計算"""
        R    = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a    = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
            * math.sin(dlng / 2) ** 2
        )
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
