# 종교시설 찾기 / Religious Facility Search

## What this skill does

동네·역명·랜드마크 텍스트를 기준점으로 잡고 주변 **종교시설을 거리순으로 조회**한다.
교회, 성당, 사찰을 같은 경로로 다루며 기본 대상은 교회다.

- 조회 전용이다. 등록, 연락, 방문 예약 같은 액션은 하지 않는다.
- 위치는 사용자가 제공한 텍스트만 쓴다. 자동 위치 추적을 하지 않는다.
- 공개 표면만 사용하므로 `k-skill-proxy`와 API key가 필요 없다.

## When to use

- "근처 교회 찾아줘"
- "강남역 근처 교회 알려줘"
- "명동 성당 위치가 어디야"
- "경주에 절 어디 있어?"
- "이 근처 종교시설 알려줘"
- "온누리교회 주소 알려줘"

## Inputs

- `location`: 동네·역명·랜드마크. 예: `강남역`, `성수동`, `경주`
- `--name`: 시설 이름으로 직접 검색. 예: `--name 온누리교회`
- `--type`: `교회`(기본) / `성당` / `절` / `사찰` / `전체`
- `--radius`: 기준점으로부터 최대 거리(m)
- `--limit`: 표시 개수 (기본 5, 최대 15). upstream 검색이 한 번에 최대 15건만 반환한다
- `--json`: JSON 출력

사용자가 "성당", "절", "사찰"을 명시하면 `--type`을 그에 맞게 지정한다. 종류를 특정하지
않고 "종교시설"이라고만 하면 `--type 전체`를 쓴다.

위치도 이름도 없으면 **먼저 사용자에게 위치를 묻는다.** 비대화형 자동화에서는
임의로 좁히지 말고 "입력 없음"을 명시한다.

권장 질문:

```text
어느 동네나 역 근처에서 찾을까요? (예: 강남역, 성수동)
```

## Public access path discovered

### 선택한 공개 경로

카카오맵 모바일 웹의 공개 표면 두 개를 순서대로 쓴다. 인증이 없고 API key도 필요 없다.

1. `https://m.map.kakao.com/actions/searchView?q=<검색어>`
   → 결과 HTML의 `data-cid` 속성에서 장소 id를 등장 순서대로 추출한다.
2. `https://place-api.map.kakao.com/places/panel3/<cid>`
   → 이름, 좌표(lat/lon), 도로명·지번 주소, 전화번호, 홈페이지 JSON.

두 요청 모두 브라우저 `User-Agent`가 필요하다. 없으면 403이 떨어진다. panel 요청에는
`appVersion`, `pf`, `Origin`, `Referer` 헤더를 함께 보낸다. 같은 표면을
`public-restroom-nearby`가 이미 쓰고 있다.

### 왜 이 경로인가

- **키 필요 없음**: `AGENTS.md`의 proxy 편입 규칙상 인증 없이 동작하는 공개 endpoint는
  프록시를 거치지 않고 사용자 머신에서 직접 호출한다.
- **전국 커버리지**: 지자체 공공데이터(예: 서울 종로구 교회 현황
  `https://www.data.go.kr/data/15117640/fileData.do`)는 구 단위로만 공개되어 전국
  표준데이터가 없다. 주 경로로 쓸 수 없어 참고 출처로만 둔다.
- **분류가 데이터에 있음**: 카카오 장소 분류에 `종교` 노드가 실제로 존재하고,
  이 스킬의 범위와 1:1로 대응한다.

```
교회 → name1: 문화,예술 / name2: 종교 / name3: 기독교 / name4: 교회
성당 → name1: 문화,예술 / name2: 종교 / name3: 천주교 / name4: 성당
```

`category.name2 == "종교"`로 필터하므로 이름에 "교회"가 들어간 카페·서점·출판사가
결과에 섞이지 않는다. `--type`은 그 안에서 `name3`·`name4`로 한 번 더 좁힌다.

거리는 upstream이 주는 값을 쓰지 않고 기준점 좌표와 haversine으로 직접 계산한다.

### fallback 순서

1. 기준점 해석 실패 → 거리 없이 결과 목록만 제공한다.
2. 지정한 종류가 0건 → `--type 전체`로 넓히거나 `--radius`를 걸었다면 풀고 재시도한다.
3. 검색 결과 0건 → 상위 행정구역으로 넓혀 재시도한다.
4. upstream 장애가 계속되면 결과를 지어내지 말고 실패를 그대로 알린다.

## Workflow

1. 사용자에게 위치와 시설 종류를 확인한다. 위치가 없으면 먼저 묻는다.
2. helper를 실행한다.

```bash
npx -y @nomadamas/k-skill@0 exec religious-facility-search scripts/religious_facility_search.py -- "강남역" --limit 5
```

성당:

```bash
npx -y @nomadamas/k-skill@0 exec religious-facility-search scripts/religious_facility_search.py -- "명동" --type 성당 --limit 5
```

사찰:

```bash
npx -y @nomadamas/k-skill@0 exec religious-facility-search scripts/religious_facility_search.py -- "경주" --type 절 --limit 5
```

종류를 가리지 않을 때:

```bash
npx -y @nomadamas/k-skill@0 exec religious-facility-search scripts/religious_facility_search.py -- "성수동" --type 전체 --radius 600
```

이름으로 검색:

```bash
npx -y @nomadamas/k-skill@0 exec religious-facility-search scripts/religious_facility_search.py -- --name "온누리교회"
```

3. 결과를 3~5개로 요약한다. 각 항목에 이름, 주소, 거리, 연락처를 붙인다.
4. 예배·미사·법회 시간을 물으면 **추정하지 말고** 홈페이지나 전화로 안내한다.

## Output

기준 위치와 검색어를 먼저 보여주고 거리순 목록을 출력한다.

```
기준 위치: 강남역사거리 (37.49795, 127.02764)
검색어: "강남역 교회" · 후보 15건 중 종교시설 15건 (가까운 3건 표시)

1. 강남성서침례교회  (교회 · 기독교)
   서울 서초구 강남대로55길 9-11 9층 (서초동)
   약 320m
   https://www.gnbbc.or.kr/
   지도 https://place.map.kakao.com/85095074
```

`--json`은 다음 구조로 출력한다.

```json
{
  "query": "강남역 교회",
  "anchor": { "name": "강남역사거리", "lat": 37.49795, "lon": 127.02764 },
  "scanned": 15,
  "matched": 15,
  "items": [
    {
      "id": "85095074",
      "name": "강남성서침례교회",
      "category": "교회",
      "denomination": "기독교",
      "category_group": "종교",
      "lat": 37.4975,
      "lon": 127.0272,
      "address": "서울 서초구 강남대로55길 9-11 9층 (서초동)",
      "phone": null,
      "homepage": "https://www.gnbbc.or.kr/",
      "place_url": "https://place.map.kakao.com/85095074",
      "distance_m": 320
    }
  ]
}
```

## Done when

- 기준 위치와 시설 종류를 확정하고 사용자에게 알렸다.
- `category.name2 == 종교`로 검증된 후보를 거리순 3~5개로 정리했다.
- 각 후보에 주소와, 있으면 연락처·홈페이지를 붙였다.
- 예배·미사·법회 시간을 임의로 지어내지 않고 공식 출처로 넘겼다.

## Failure modes

- **검색 결과 없음**: 검색어가 좁거나 오탈자다. 상위 행정구역으로 넓혀 재시도한다.
- **지정 종류 0건**: 후보는 잡혔지만 해당 종류가 없다. `--type 전체`로 넓히거나, `--radius`를 걸었다면 풀고 확인한다. `--radius`는 결과를 좁히는 옵션이라 늘려도 새 후보를 가져오지 않는다.
- **HTTP 403**: `User-Agent` 누락. helper가 헤더를 넣으므로 직접 호출할 때만 발생한다.
- **HTTP 5xx / 타임아웃**: upstream 일시 장애. 재시도하고 계속 실패하면 그대로 보고한다.
- **upstream 구조 변경**: `data-cid` 패턴이나 panel JSON 스키마가 바뀌면 결과가 0건이 된다.
  공식 문서가 있는 API가 아니므로 이 실패 모드는 상수로 존재한다.
- **좌표 입력**: v1은 `위도,경도` 입력을 지원하지 않는다. helper가 명시적으로 거부하고
  동네·역명을 요구한다.
- **예배·미사·법회 시간**: upstream `open_hours`가 비어 있다. 제공하지 않는다.

## Notes

- 공개 정보 조회 전용이다. 종교나 교단의 우열을 평가하거나 이단 여부를 판별하지 않는다.
- 특정 시설이나 교단을 권유하지 않는다. 거리와 공개 정보만 근거로 나열한다.
- 예배·미사·법회 시간, 성직자, 교단 소속은 이 데이터에 없다. 추정하지 않고 공식 출처로 넘긴다.
- 사용자가 제공한 위치 텍스트만 쓴다. 위치를 자동으로 알아내려 하지 않는다.
