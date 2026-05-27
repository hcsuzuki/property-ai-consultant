import os
import math
import datetime
import requests
from collections import Counter
from typing import Optional


class PropertyDataFetcher:
    """Zillow API + Google Maps API からデータ取得"""

    ZILLOW_HOST = "real-estate-zillow-com.p.rapidapi.com"
    MAPS_BASE = "https://maps.googleapis.com/maps/api"

    def __init__(self):
        self.rapidapi_key = os.getenv("RAPIDAPI_KEY", "")
        self.google_key = os.getenv("GOOGLE_MAPS_API_KEY", "")

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
            "X-RapidAPI-Key": self.rapidapi_key,
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
            "X-RapidAPI-Key": self.rapidapi_key,
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

        # 住所コンポーネントから市・州を抽出
        city = state = ""
        for comp in geocode.get("components", []):
            types = comp.get("types", [])
            if "locality" in types:
                city = comp.get("long_name", "")
            if "administrative_area_level_1" in types:
                state = comp.get("short_name", "")

        return {
            "geocode": geocode,
            "city": city,
            "state": state,
            "schools": self._nearby_places(lat, lng, "school", radius=2400),
            "supermarkets": self._nearby_places(lat, lng, "grocery_or_supermarket", radius=2400),
            "shopping": self._nearby_places(lat, lng, "shopping_mall", radius=3200),
            "restaurants": self._nearby_places(lat, lng, "restaurant", radius=1600),
            "transit": self._nearby_places(lat, lng, "transit_station", radius=1600),
            "road_info": self._check_road(lat, lng),
            "crime": self.get_crime_data(lat, lng, city, state),
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Crime data
    # ──────────────────────────────────────────────────────────────────────────

    def get_crime_data(self, lat: float, lng: float, city: str = "", state: str = "") -> dict:
        """犯罪データを取得（現在はシカゴのみ対応）"""
        if "CHICAGO" in city.upper() or ("IL" in state.upper() and 41.6 < lat < 42.1):
            return self._get_chicago_crime(lat, lng)
        if city:
            return {
                "error": f"犯罪データは現在シカゴのみ対応（{city}は未対応）",
                "safety_score": None,
            }
        return {"error": "犯罪データ未対応エリア", "safety_score": None}

    def _get_chicago_crime(self, lat: float, lng: float, radius_m: int = 800) -> dict:
        """Chicago Data Portal から過去1年の犯罪データを取得（無料・API key不要）"""
        lat_d = radius_m / 111_000
        lng_d = radius_m / (111_000 * math.cos(math.radians(lat)))
        year = datetime.datetime.now().year - 1
        try:
            resp = requests.get(
                "https://data.cityofchicago.org/resource/ijzp-q8t2.json",
                params={
                    "$where": (
                        f"latitude > '{lat - lat_d:.6f}' AND latitude < '{lat + lat_d:.6f}' "
                        f"AND longitude > '{lng - lng_d:.6f}' AND longitude < '{lng + lng_d:.6f}' "
                        f"AND year = '{year}'"
                    ),
                    "$limit": 500,
                    "$select": "primary_type",
                },
                timeout=15,
            )
            data = resp.json()
            if isinstance(data, list):
                total = len(data)
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
                r = data["results"][0]
                loc = r["geometry"]["location"]
                return {
                    "lat": loc["lat"],
                    "lng": loc["lng"],
                    "formatted_address": r["formatted_address"],
                    "components": r.get("address_components", []),
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
                    "radius": radius,
                    "type": place_type,
                    "key": self.google_key,
                },
                timeout=10,
            )
            results = resp.json().get("results", [])[:5]
            places = []
            for p in results:
                plat = p["geometry"]["location"]["lat"]
                plng = p["geometry"]["location"]["lng"]
                dist_km = self._haversine(lat, lng, plat, plng)
                places.append({
                    "name": p.get("name", ""),
                    "distance_miles": round(dist_km * 0.621371, 2),
                    "distance_km": round(dist_km, 2),
                    "rating": p.get("rating"),
                    "vicinity": p.get("vicinity", ""),
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
                    "latlng": f"{lat},{lng}",
                    "key": self.google_key,
                    "result_type": "route",
                },
                timeout=10,
            )
            for result in resp.json().get("results", []):
                for comp in result.get("address_components", []):
                    if "route" in comp.get("types", []):
                        road_name = comp.get("long_name", "")
                        is_major = any(kw in road_name.upper() for kw in MAJOR_KEYWORDS)
                        return {"road_name": road_name, "is_major_road": is_major}
        except Exception:
            pass
        return {"road_name": "不明", "is_major_road": False}

    @staticmethod
    def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """2点間の距離(km)をHaversine公式で計算"""
        R = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a = (math.sin(dlat / 2) ** 2
             + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
             * math.sin(dlng / 2) ** 2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
