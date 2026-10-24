# Perpetual Alpha — PAS Pair-Reversion Agent

## 한국어

Perpetual Alpha 2026 대회를 위해 만든 **PAS DEX Hyperliquid Testnet 전용** 페어 평균회귀 연구·실행 프로젝트입니다. BTC–EWY와 BTC–ETH의 상대 가격 괴리를 이용하되, 두 다리를 같은 달러 금액으로 구성해 시장 방향 노출을 낮추는 것을 목표로 합니다.

### 현재 전략 요약

| 항목 | BTC–EWY | BTC–ETH |
|---|---:|---:|
| 전략 비중 | 85% | 15% |
| 롤링 상관관계 창 | 24시간 | 72시간 |
| 수익률 비교 시차 | 12시간 | 3시간 |
| 상관관계 최소값 | 0.70 | 0.70 |
| 진입 괴리 최소값 | 1.5% | 1.5% |
| 목표 회복 | 100% | 50% |
| 최대 보유 | 12시간 | 24시간 |

- 총 익스포저: 계좌 가치의 65% (양 다리를 같은 달러 금액으로 구성)
- BTC 24시간 실현 변동성이 0.6% 이상이면 신규 진입 규모를 75%로 축소
- 일일 손실 제한: -3%; 고점 대비 손실 제한: -6%
- 모든 신호는 아직 진행 중인 캔들이 아닌 **완성된 시간봉**만 사용

### 저장소 구성

```text
pas_pairs_shadow.py              # 공개 시세만 읽는 관찰·신호 계산기
pas_pairs_live.py                # PAS Testnet 전용 실행기
official_score_validation.py     # 공식 점수식 기반 과거 검증
pas_pairs_config.json            # 전략 파라미터 예시
pas_pairs_live_config.json
.env.example                     # 비밀값 없이 환경 변수 형식만 제공
requirements.txt
docs/
  TECHNICAL_REPORT_KO.md
  TECHNICAL_REPORT_EN.md
```

### 빠른 시작

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
python pas_pairs_shadow.py --once
set HISTORY_DIR=C:\\path\\to\\history
python official_score_validation.py
```

실행 주문 경로는 Testnet 전용이며, 별도 API 지갑과 명시적인 이중 실행 플래그를 요구합니다. 실제 개인키는 `.env`에만 보관하고 절대로 커밋하지 마세요. `pas_pairs_live.py`를 실행하기 전에 PAS DEX 규칙과 대회 규칙을 직접 확인해야 합니다.

`official_score_validation.py`는 오프라인 연구용이다. `HISTORY_DIR`에 시간봉 `BTC.csv`, `ETH.csv`, `EWY.csv`가 있어야 하며, 시장 이력 파일은 이 저장소에 포함하지 않는다.

### 주의

이 저장소는 연구·교육 목적으로 제공됩니다. 과거 검증은 미래 성과를 보장하지 않으며, 역사 데이터의 체결가격·수수료·슬리피지와 대회 환경은 다를 수 있습니다. 메인넷 사용, 출금 기능, 개인키 공유를 위한 코드가 아닙니다.

---

## English

This is a **PAS DEX Hyperliquid Testnet-only** pair-reversion research and execution project for Perpetual Alpha 2026. It trades the relative dislocation of BTC–EWY and BTC–ETH while using equal-dollar legs to reduce outright market-direction exposure.

### Current strategy summary

| Item | BTC–EWY | BTC–ETH |
|---|---:|---:|
| Strategy weight | 85% | 15% |
| Rolling correlation window | 24 hours | 72 hours |
| Return-comparison lag | 12 hours | 3 hours |
| Minimum correlation | 0.70 | 0.70 |
| Minimum entry gap | 1.5% | 1.5% |
| Target recovery | 100% | 50% |
| Maximum holding time | 12 hours | 24 hours |

- Gross exposure: 65% of account equity, split into equal-dollar legs
- New entries are scaled to 75% when 24-hour BTC realized volatility is at least 0.6%
- Daily loss limit: -3%; peak-to-trough guard: -6%
- Signals use completed hourly candles only, never the still-forming candle

### Repository layout

```text
pas_pairs_shadow.py              # Public-data-only signal monitor
pas_pairs_live.py                # PAS Testnet execution runner
official_score_validation.py     # Historical validation using the official score formula
pas_pairs_config.json            # Strategy parameter example
pas_pairs_live_config.json
.env.example                     # Variable names only; no secrets
requirements.txt
docs/
  TECHNICAL_REPORT_KO.md
  TECHNICAL_REPORT_EN.md
```

### Quick start

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
python pas_pairs_shadow.py --once
set HISTORY_DIR=C:\\path\\to\\history
python official_score_validation.py
```

The order path is restricted to Testnet and requires a separate API wallet plus two explicit command-line gates. Keep real private keys only in a local `.env` file and never commit them. Read the PAS DEX and competition rules before using `pas_pairs_live.py`.

`official_score_validation.py` is an offline study. It requires hourly `BTC.csv`, `ETH.csv`, and `EWY.csv` under `HISTORY_DIR`; market-history files are deliberately not included in this repository.

### Disclaimer

This repository is for research and educational use. Historical results do not guarantee future performance; historical prices, fees, slippage, and the competition environment may differ. It is not designed for mainnet trading, withdrawals, or sharing private keys.
