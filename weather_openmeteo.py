# -*- coding: utf-8 -*-
"""
Open-Meteo API (https://open-meteo.com/) から天気予報を取得するモジュール。
気象庁の非公式JSON API(weather_jma.py)の代替。

- APIキー不要
- 気象庁の高解像度モデル(jma_seamless)に加え、ECMWF(ecmwf_ifs025)・
  NOAA GFS(gfs_seamless)を平均することで単一モデルの偏りを緩和する
  (config.WEATHER_MODELSで変更可能)
- 公式ドキュメント: https://open-meteo.com/en/docs

エンドポイント例(東京駅、複数モデル指定):
    https://api.open-meteo.com/v1/forecast
        ?latitude=35.6812&longitude=139.7671
        &hourly=temperature_2m,precipitation_probability,weather_code
        &daily=temperature_2m_max
        &current=temperature_2m
        &timezone=Asia%2FTokyo
        &models=jma_seamless,ecmwf_ifs025,gfs_seamless
        &forecast_days=2

複数モデルを指定すると、各変数名に "_<モデルID>" のサフィックスが付いた
キーで結果が返る(例: temperature_2m_max_ecmwf_ifs025)。
本モジュールはこれらを平均して単一の値にまとめる。
"""
import threading
import time
from datetime import datetime

import requests

import config

# widgets.py側の描画で使うアイコン種別(weather_jma.pyと同じ名前を維持し、
# 呼び出し側の互換性を保つ)
ICON_SUNNY = "sunny"
ICON_CLOUDY = "cloudy"
ICON_RAIN = "rain"
ICON_SUN_CLOUD = "sun_cloud"

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# WMO Weather interpretation codes -> 内部アイコン種別への対応表
# https://open-meteo.com/en/docs (Weather variable documentation内のWMO表)
_WMO_ICON_MAP = {
    0: ICON_SUNNY,      # 快晴
    1: ICON_SUN_CLOUD,  # 晴れ(概ね)
    2: ICON_SUN_CLOUD,  # 一部曇り
    3: ICON_CLOUDY,     # 曇り
    45: ICON_CLOUDY,    # 霧
    48: ICON_CLOUDY,    # 霧氷を伴う霧
    51: ICON_RAIN,       # 弱い霧雨
    53: ICON_RAIN,       # 霧雨
    55: ICON_RAIN,       # 強い霧雨
    56: ICON_RAIN,       # 弱い着氷性の霧雨
    57: ICON_RAIN,       # 着氷性の霧雨
    61: ICON_RAIN,       # 弱い雨
    63: ICON_RAIN,       # 雨
    65: ICON_RAIN,       # 強い雨
    66: ICON_RAIN,       # 弱い着氷性の雨
    67: ICON_RAIN,       # 着氷性の雨
    71: ICON_CLOUDY,     # 弱い雪
    73: ICON_CLOUDY,     # 雪
    75: ICON_CLOUDY,     # 強い雪
    77: ICON_CLOUDY,     # 雪粒
    80: ICON_RAIN,       # 弱いにわか雨
    81: ICON_RAIN,       # にわか雨
    82: ICON_RAIN,       # 激しいにわか雨
    85: ICON_CLOUDY,     # 弱いにわか雪
    86: ICON_CLOUDY,     # 激しいにわか雪
    95: ICON_RAIN,       # 雷雨
    96: ICON_RAIN,       # 雷雨(弱い雹を伴う)
    99: ICON_RAIN,       # 雷雨(強い雹を伴う)
}


def _icon_from_code(code, is_daytime):
    icon = _WMO_ICON_MAP.get(code, ICON_CLOUDY)
    # 快晴/晴れ系は夜間なら曇りアイコンに寄せる(太陽アイコンを夜に出さない)
    if icon in (ICON_SUNNY, ICON_SUN_CLOUD) and not is_daytime:
        return ICON_CLOUDY
    return icon


class WeatherOpenMeteo:
    """Open-Meteo APIから天気予報を取得するクラス。
    メソッド名・戻り値の構造はweather_jma.WeatherJMAと互換なので、
    main.py / widgets.py 側の変更は import 文の差し替えのみで済む。
    """

    def __init__(self, latitude=None, longitude=None):
        self.latitude = latitude if latitude is not None else config.LATITUDE
        self.longitude = longitude if longitude is not None else config.LONGITUDE
        self.temp_current = None
        self.temp_max = None
        # [{"time": datetime, "pop": int, "icon": str}, ...] 最大8件
        self.forecast_slots = []
        self._lock = threading.Lock()
        self._running = False
        self._last_error = None

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                self._fetch_and_parse()
                self._last_error = None
            except Exception as e:  # ネットワーク断・仕様変更などに耐える
                self._last_error = str(e)
            time.sleep(config.WEATHER_UPDATE_INTERVAL_SEC)

    def _build_params(self):
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "hourly": "temperature_2m,precipitation_probability,weather_code",
            "daily": "temperature_2m_max",
            "current": "temperature_2m",
            "timezone": "Asia/Tokyo",
            "models": ",".join(config.WEATHER_MODELS),
            "forecast_days": 2,
        }

    def _fetch_and_parse(self):
        resp = requests.get(OPEN_METEO_URL, params=self._build_params(), timeout=10)
        resp.raise_for_status()
        data = resp.json()

        temp_max = self._parse_daily(data)
        temp_current = self._parse_current(data)
        slots = self._parse_hourly(data)

        with self._lock:
            if temp_current is not None:
                self.temp_current = temp_current
            if temp_max is not None:
                self.temp_max = temp_max
            if slots:
                self.forecast_slots = slots

    @staticmethod
    def _series_for_model(block, var_name, model_id):
        """複数モデル指定時、Open-Meteoは各変数名に"_<モデルID>"の
        サフィックスを付けて返す(例: temperature_2m_max_ecmwf_ifs025)。
        モデルを1つしか指定していない場合や、地域によってそのモデルの
        データが無い場合はサフィックス無しのキーにフォールバックする。
        """
        suffixed = block.get(f"{var_name}_{model_id}")
        if suffixed is not None:
            return suffixed
        return block.get(var_name)

    def _collect_model_values(self, block, var_name, index):
        """指定インデックスの値を、利用可能な全モデルから集めてリストで返す
        (欠損しているモデルはスキップする)。
        """
        values = []
        for model_id in config.WEATHER_MODELS:
            series = self._series_for_model(block, var_name, model_id)
            if series is None:
                continue
            try:
                v = series[index]
            except (IndexError, TypeError):
                continue
            if v is not None:
                values.append(v)
        return values

    def _parse_daily(self, data):
        try:
            daily = data["daily"]
            max_values = self._collect_model_values(daily, "temperature_2m_max", 0)
            return round(sum(max_values) / len(max_values)) if max_values else None
        except (KeyError, IndexError, TypeError, ZeroDivisionError):
            return None

    def _collect_current_values(self, block, var_name):
        """"current"ブロックは時系列ではなく単一値なので、
        _collect_model_values()のインデックス版とは別に、各モデルの値を
        そのまま集めてリストで返す(欠損しているモデルはスキップする)。
        """
        values = []
        for model_id in config.WEATHER_MODELS:
            v = self._series_for_model(block, var_name, model_id)
            if v is not None:
                values.append(v)
        return values

    def _parse_current(self, data):
        try:
            current = data["current"]
            values = self._collect_current_values(current, "temperature_2m")
            return round(sum(values) / len(values)) if values else None
        except (KeyError, TypeError, ZeroDivisionError):
            return None

    def _pick_icon_code(self, hourly, index):
        """天気コードは数値の平均に意味が無いため、config.WEATHER_MODELSの
        先頭から順に、値が取れたモデルのコードを採用する(気象庁モデル優先)。
        """
        for model_id in config.WEATHER_MODELS:
            series = self._series_for_model(hourly, "weather_code", model_id)
            if series is None:
                continue
            try:
                v = series[index]
            except (IndexError, TypeError):
                continue
            if v is not None:
                return int(v)
        return None

    def _parse_hourly(self, data):
        """直近の時刻から3時間おきに8コマ(=24時間分)を取り出す。
        降水確率・気温は複数モデルの平均、天気コードはモデル優先順位で採用する。
        1時間おきにしたい場合はconfig.WEATHER_SLOT_STEP_HOURSを1に変更する。
        """
        try:
            hourly = data["hourly"]
            times = hourly["time"]  # 時刻軸はモデル間で共通

            now = datetime.now()
            # 現在時刻以降で最初のインデックスを探す
            start_idx = 0
            for i, t_str in enumerate(times):
                t = datetime.fromisoformat(t_str)
                if t >= now.replace(minute=0, second=0, microsecond=0):
                    start_idx = i
                    break

            step = config.WEATHER_SLOT_STEP_HOURS
            slots = []
            for i in range(start_idx, len(times), step):
                if len(slots) >= 8:
                    break
                t = datetime.fromisoformat(times[i])

                pop_values = self._collect_model_values(hourly, "precipitation_probability", i)
                pop = round(sum(pop_values) / len(pop_values)) if pop_values else 0

                code = self._pick_icon_code(hourly, i)
                if code is None:
                    code = 3  # 取得できなければ「曇り」扱い
                is_daytime = 6 <= t.hour < 18
                icon = _icon_from_code(code, is_daytime)

                slot = {"time": t, "pop": pop, "icon": icon}

                temp_values = self._collect_model_values(hourly, "temperature_2m", i)
                if temp_values:
                    slot["temp"] = round(sum(temp_values) / len(temp_values))

                slots.append(slot)
            return slots
        except (KeyError, IndexError, ValueError, TypeError):
            return []

    def get(self):
        with self._lock:
            return {
                "temp_current": self.temp_current,
                "temp_max": self.temp_max,
                "slots": list(self.forecast_slots),
                "error": self._last_error,
            }


if __name__ == "__main__":
    # 単体テスト用: python weather_openmeteo.py で動作確認できる
    w = WeatherOpenMeteo()
    w._fetch_and_parse()
    import pprint
    pprint.pprint(w.get())
