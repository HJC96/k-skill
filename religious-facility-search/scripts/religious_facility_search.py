#!/usr/bin/env python3
"""종교시설 찾기 — Kakao 공개 모바일 지도 표면 기반 (API 키 불필요).

공개 접근 경로:
  1) m.map.kakao.com/actions/searchView  → 검색 결과 HTML에서 place id(cid) 추출
  2) place-api.map.kakao.com/places/panel3/<cid> → 이름·좌표·주소·전화·홈페이지 JSON

Kakao 장소 분류의 category.name2 == "종교" 로 필터하므로
이름에 "교회"가 들어간 카페·서점 같은 오탐이 걸러진다.
"""

import argparse
import json
import math
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

SEARCH_VIEW_URL = "https://m.map.kakao.com/actions/searchView"
PLACE_PANEL_URL = "https://place-api.map.kakao.com/places/panel3"
PLACE_PAGE_URL = "https://place.map.kakao.com"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)
BROWSER_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "ko,en-US;q=0.9,en;q=0.8",
    "user-agent": USER_AGENT,
}
PANEL_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "ko,en-US;q=0.9,en;q=0.8",
    "user-agent": USER_AGENT,
    "appVersion": "6.6.0",
    "pf": "PC",
    "origin": "https://place.map.kakao.com",
    "referer": "https://place.map.kakao.com/",
}

RELIGION_CATEGORY = "종교"
TYPE_ALIASES = {
    "교회": ["교회"],
    "성당": ["성당"],
    "절": ["절", "사찰"],
    "사찰": ["절", "사찰"],
    "전체": [],
}
COORD_RE = re.compile(r"^\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)\s*$")
CID_RE = re.compile(r'data-cid="(\d+)"')
MAX_CANDIDATES = 15  # upstream searchView가 한 번에 돌려주는 최대 장소 수


class LookupError_(Exception):
    """조회 실패를 명시적 실패 모드로 올린다."""


def fetch(url, headers, timeout=15, as_json=False):
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        raise LookupError_(f"HTTP {error.code} from {urllib.parse.urlsplit(url).netloc}") from error
    except urllib.error.URLError as error:
        raise LookupError_(f"네트워크 오류: {error.reason}") from error

    if as_json:
        try:
            return json.loads(raw)
        except json.JSONDecodeError as error:
            raise LookupError_("장소 상세 응답이 JSON이 아니다 (upstream 변경 가능)") from error
    return raw


def search_place_ids(query, limit=MAX_CANDIDATES):
    url = f"{SEARCH_VIEW_URL}?{urllib.parse.urlencode({'q': query})}"
    html = fetch(url, BROWSER_HEADERS)

    seen, ids = set(), []
    for cid in CID_RE.findall(html):
        if cid not in seen:
            seen.add(cid)
            ids.append(cid)
        if len(ids) >= limit:
            break
    return ids


def fetch_place(cid):
    try:
        payload = fetch(f"{PLACE_PANEL_URL}/{cid}", PANEL_HEADERS, as_json=True)
    except LookupError_:
        return None

    summary = payload.get("summary") or {}
    point = summary.get("point") or {}
    address = summary.get("address") or {}
    category = summary.get("category") or {}
    if not summary.get("name") or not point.get("lat"):
        return None

    phones = [p.get("tel") for p in (summary.get("phone_numbers") or []) if p.get("type") != "FAX"]
    return {
        "id": cid,
        "name": summary.get("name"),
        "category": category.get("name4") or category.get("name"),
        "denomination": category.get("name3"),
        "category_group": category.get("name2"),
        "lat": point.get("lat"),
        "lon": point.get("lon"),
        "address": address.get("disp") or address.get("road"),
        "jibun": address.get("jibun"),
        "phone": phones[0] if phones else None,
        "homepage": (summary.get("homepages") or [None])[0],
        "place_url": f"{PLACE_PAGE_URL}/{cid}",
    }


def haversine_m(lat1, lon1, lat2, lon2):
    radius = 6371000.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    )
    return radius * 2 * math.asin(math.sqrt(a))


def anchor_score(place, location):
    """검색어에 가까운 이름일수록 좋은 기준점. (점수, 이름길이, 등장순서)로 정렬한다."""
    name = (place.get("name") or "").replace(" ", "")
    target = location.replace(" ", "")
    if name == target:
        return 0
    if name.startswith(target):
        return 1
    if target in name:
        return 2
    return 3


def resolve_anchor(location):
    """위치 문자열을 좌표로 바꾼다. 실패하면 None (거리 없이 결과만 제공)."""
    candidates = []
    for order, cid in enumerate(search_place_ids(location, limit=6)):
        place = fetch_place(cid)
        if place:
            candidates.append((anchor_score(place, location), len(place["name"]), order, place))

    if not candidates:
        return None

    best = min(candidates)[3]
    return {"name": best["name"], "lat": best["lat"], "lon": best["lon"]}


def matches_type(place, facility_type):
    if place.get("category_group") != RELIGION_CATEGORY:
        return False
    wanted = TYPE_ALIASES.get(facility_type, [facility_type])
    if not wanted:
        return True
    haystack = f"{place.get('category') or ''} {place.get('denomination') or ''}"
    return any(token in haystack for token in wanted)


def collect(query, facility_type, anchor, radius_m, limit):
    ids = search_place_ids(query)
    if not ids:
        raise LookupError_(f'"{query}" 검색 결과가 비었다 (검색어를 넓히거나 지역명을 붙여볼 것)')

    with ThreadPoolExecutor(max_workers=4) as pool:
        places = [p for p in pool.map(fetch_place, ids) if p]

    places = [p for p in places if matches_type(p, facility_type)]

    if anchor:
        for place in places:
            place["distance_m"] = round(haversine_m(anchor["lat"], anchor["lon"], place["lat"], place["lon"]))
        if radius_m:
            places = [p for p in places if p["distance_m"] <= radius_m]
        places.sort(key=lambda p: p["distance_m"])

    return len(ids), len(places), places[:limit]


def format_report(query, anchor, scanned, matched, places, facility_type):
    lines = []
    if anchor:
        lines.append(f"기준 위치: {anchor['name']} ({anchor['lat']:.5f}, {anchor['lon']:.5f})")
    summary = f'검색어: "{query}" · 후보 {scanned}건 중 종교시설 {matched}건'
    if matched > len(places):
        summary += f" (가까운 {len(places)}건 표시)"
    lines.append(summary)
    lines.append("")

    if not places:
        lines.append(f"조건에 맞는 {facility_type}을(를) 찾지 못했다. 지역을 넓혀 다시 찾거나 "
                     f"--type 전체 로 확인할 것 (--radius 는 결과를 좁히는 옵션이다).")
        return "\n".join(lines)

    for index, place in enumerate(places, start=1):
        label = place["category"] or "종교시설"
        if place.get("denomination"):
            label = f"{label} · {place['denomination']}"
        lines.append(f"{index}. {place['name']}  ({label})")
        if place.get("address"):
            lines.append(f"   {place['address']}")
        if place.get("distance_m") is not None:
            lines.append(f"   약 {place['distance_m']:,}m")
        contact = []
        if place.get("phone"):
            contact.append(f"전화 {place['phone']}")
        if place.get("homepage"):
            contact.append(place["homepage"])
        if contact:
            lines.append("   " + "  ".join(contact))
        lines.append(f"   지도 {place['place_url']}")
        lines.append("")

    lines.append("예배·미사·법회 시간은 이 데이터에 없다. 각 홈페이지나 전화로 확인할 것.")
    return "\n".join(lines).rstrip()


def main():
    parser = argparse.ArgumentParser(description="종교시설 찾기 (Kakao 공개 표면, API 키 불필요)")
    parser.add_argument("location", nargs="?", help="동네·역명·랜드마크 (예: 강남역, 성수동)")
    parser.add_argument("--name", help="교회/시설 이름으로 직접 검색")
    parser.add_argument("--type", default="교회", choices=sorted(TYPE_ALIASES), help="시설 종류 (기본: 교회)")
    parser.add_argument("--radius", type=int, help="기준 위치로부터 최대 거리(m)")
    parser.add_argument("--limit", type=int, default=5, help="표시 개수 (기본 5, 최대 15)")
    parser.add_argument("--json", action="store_true", help="JSON으로 출력")
    args = parser.parse_args()

    if not args.location and not args.name:
        parser.error("location 또는 --name 중 하나는 필요하다. 사용자에게 현재 위치를 먼저 물어볼 것.")

    if not 1 <= args.limit <= MAX_CANDIDATES:
        parser.error(f"--limit은 1~{MAX_CANDIDATES} 사이여야 한다. upstream 검색이 한 번에 최대 "
                     f"{MAX_CANDIDATES}건만 반환하므로 그보다 많이 표시할 수 없다.")

    if args.location and COORD_RE.match(args.location):
        parser.error("좌표 검색은 지원하지 않는다. 동네·역명·랜드마크로 입력할 것 (예: 강남역, 성수동).")

    if args.name:
        query = f"{args.location} {args.name}".strip() if args.location else args.name
    else:
        query = f"{args.location} {args.type}"

    try:
        anchor = resolve_anchor(args.location) if args.location else None
        scanned, matched, places = collect(query, args.type, anchor, args.radius, args.limit)
    except LookupError_ as error:
        print(f"조회 실패: {error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"query": query, "anchor": anchor, "scanned": scanned,
                          "matched": matched, "items": places},
                         ensure_ascii=False, indent=2))
    else:
        print(format_report(query, anchor, scanned, matched, places, args.type))
    return 0


if __name__ == "__main__":
    sys.exit(main())
