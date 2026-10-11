# WHT_DYNEVAL — 동역학 해석-시험 정합도 평가 엔진

1D/3D 시계열 데이터(변위·속도)의 정합도를 100% 만점 체계로 평가하고,
SciPy 최적화 루프와 연동되는 목적함수를 제공하는 Python 패키지입니다.

## 🌐 결과 보고서 (GitHub Pages)

- **[동역학 정합도 평가지표 백과사전](https://wonholee1.github.io/WHT_DYNEVAL/)** — 지표 총람, 1D/3D 스위프 실측, 최적화 연동 데모
- v2 복합악조건판, 다크/인쇄 프리셋은 [`reports/`](reports/) 폴더 참조

## 구성

| 경로 | 내용 |
|---|---|
| `dyneval/evaluator.py` | `ComprehensiveDynamicEvaluator` — S&G, 경량 CORA, DTW, ATE, Hausdorff, Fréchet, Procrustes, `calc_loss` |
| `dyneval/signals.py` | 위상/크기/형태/방향 노브 임의 신호 생성기 (1D 낙하·3D 궤적) |
| `dyneval/optimize.py` | `optimize_dynamic_parameters` — SciPy 연동 보정 래퍼 |
| `scripts/make_encyclopedia_report.py` | HTML 보고서 생성 (`--preset lab|midnight|paper`, `--only-v2`) |
| `tests/test_sweep.py` | 지표 스위프 스모크 테스트 6종 |
| `my_plan_dyneval.md` | 기획 대화 원문 (수식 개행 보정됨) |

## 빠른 시작

```powershell
pip install numpy scipy matplotlib koreanize-matplotlib pytest
python -m pytest tests/ -q
python scripts/make_encyclopedia_report.py --preset lab
```

## 평가 체계 요약

- 변위 Headline: NRMSE (1D) / Spatial ATE (3D)
- 속도 Headline: Sprague & Geers (1D/3D 벡터)
- 원인 분해: CORA 3축 (Kp/Kv/Kg) + 축별 부록
- 최적화: `calc_loss`로 수렴 → `evaluate` 100% 보고서로 판정
