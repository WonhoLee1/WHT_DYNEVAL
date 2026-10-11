# WHT_DYNEVAL — 동역학 해석-시험 정합도 평가 엔진

낙하·충돌·진동 같은 동역학 시계열 데이터에 대해,
수치해석 결과와 시험 계측의 일치도를 **100% 만점 체계**로 평가하고
파라미터 역동정(캘리브레이션)까지 연동하는 Python 패키지입니다.

## 🌐 결과 보고서 (GitHub Pages)

- **[동역학 정합도 평가지표 백과사전](https://wonholee1.github.io/WHT_DYNEVAL/)** — 본편 (이론편 + 1D/3D 스위프 + 복합악조건 v2 + 최적화 연동)
- v2 요약판·다크/인쇄 프리셋: [`reports/`](reports/) — `*_v2.html`, `*_midnight.html`, `*_paper.html`

## 왜 이 패키지인가

| 문제 | 해법 |
|---|---|
| 점별 RMSE는 위상 20ms 어긋남에 폭락, 진폭 오차는 못 봄 | 크기(M)/위상(P) 분리 지표 (Sprague & Geers) |
| R²·상관계수가 좋아 보여도 실제론 불일치 | 분모 의존성 문서화 + 고정 물리량 Headline |
| 최적화 Loss와 보고 점수가 따로 놈 | 2단계 파이프라인 (`calc_loss` 수렴 → `evaluate` 100% 판정, 4조합 실측 검증) |
| 3D 궤적 축별 평균의 왜곡 | 벡터 놈·내적 기반 통합 지표 + 축별 부록 |

## 평가 체계

| 차원 | 변위 Headline | 속도 Headline | 원인 분해 부록 |
|---|---|---|---|
| 1D | Global NRMSE (기준폭 Δx) | Sprague & Geers (에너지 적분) | CORA 3축 Kp(지연)/Kv(형상)/Kg(크기), DTW, R²/Corr |
| 3D | Spatial ATE (L_diag) | Vector S&G (벡터내적 확장) | Hausdorff, Fréchet, Procrustes, 축별 RMSE/R²/Corr |

- 모든 Headline: `max(0, 1 − 오차/기준척도) × 100`, 완전일치 100%
- 최적화 Loss (미분 가능, 보고용 아님): 속도 `0.4·L2+0.3·피크²+0.3·면적²`, 변위 `0.7·L2+0.3·피크²`
- 상대치 지표 주의: R²·Corr·개별 Range NRMSE는 분모(분산·표준편차·자가폭)에 따라 같은 오차도 다르게 보임 → 지배축(분산점유율 20%↑)에서만 판정 근거로 사용

## 빠른 시작

```powershell
pip install numpy scipy matplotlib koreanize-matplotlib pytest
python -m pytest tests/ -q
```

## 사용 예시

```python
import numpy as np
from dyneval import ComprehensiveDynamicEvaluator
from dyneval.signals import make_1d_drop_signals, make_3d_trajectory_signals
from dyneval.optimize import optimize_dynamic_parameters

t = np.linspace(0, 1.5, 400)
sig = make_1d_drop_signals(t, delay=0.02, mag=1.1)  # 위상·크기 오차 주입

# 1) 보고서용 100% 평가
ev = ComprehensiveDynamicEvaluator(t, sig["vel_exp"], mode="vel")
print(ev.evaluate(sig["vel_sim"])["Main_Headline_Accuracy(%)"])
print(ev.evaluate(sig["vel_sim"])["CORA_Light_Decomposition"])

# 2) 최적화용 매끄러운 손실 + 파라미터 보정
def sim_func(params, tt):
    s = make_1d_drop_signals(tt, mag=params[0], delay=params[1])
    return s["vel_sim"]

out = optimize_dynamic_parameters(
    sim_func, np.array([0.8, 0.05]), t, sig["vel_exp"],
    mode="vel", bounds=[(0.7, 1.3), (-0.02, 0.08)])
print(out["optimal_params"], out["calibrated_accuracy(%)"])

# 3) 3D 궤적 (N, 3) — 모드 자동 판별, L_diag 자동 산출
sig3 = make_3d_trajectory_signals(t, shape_detune=3.0)
ev3 = ComprehensiveDynamicEvaluator(t, sig3["disp_exp"], mode="disp")
print(ev3.evaluate(sig3["disp_sim"])["Axis_Metrics"])  # 축별 부록
```

## 보고서 재생성

```powershell
# 본편 (이론+스위프+v2+최적화)
python scripts/make_encyclopedia_report.py --preset lab
# 프리셋: lab(기본) | midnight(다크) | paper(인쇄 흑백)
python scripts/make_encyclopedia_report.py --preset midnight --out reports/dyneval_midnight.html
# v2 요약판만
python scripts/make_encyclopedia_report.py --only-v2
```

사이트(`index.html`)는 본편 lab 결과물의 복사본입니다. 보고서 갱신 후 Pages 반영:

```powershell
Copy-Item reports/dyneval_encyclopedia.html index.html
git add -A; git commit -m "Update report"; git push origin main
```

## 구성

| 경로 | 내용 |
|---|---|
| `dyneval/evaluator.py` | `ComprehensiveDynamicEvaluator` — 1D/3D × 변위/속도 통합 엔진 |
| `dyneval/signals.py` | `make_1d_drop_signals`, `make_3d_trajectory_signals` — 위상/크기/형태/방향 노브 |
| `dyneval/optimize.py` | `optimize_dynamic_parameters` — 발산 방어 내장 SciPy 래퍼 |
| `scripts/make_encyclopedia_report.py` | HTML 보고서 생성기 (스위프+그래프+표, `--preset`, `--only-v2`) |
| `tests/test_sweep.py` | 스모크 테스트 6종 (동일신호 100%, 위상단조, M/P분리, Corr맹점, 예외, 최적화수렴) |
| `my_plan_dyneval.md` | 기획 대화 원문 (수식 개행 보정됨) |
| `dev_log/` | 작업일지 |

## 이론적 배경

상세 수식과 지표별 0% 기준은 보고서 **§1+ 이론편** 참조.
설계 원칙 3가지:

1. **Headline 분모는 고정 물리량만** — NRMSE(Δx·L_diag), S&G(적분 에너지). 케이스·축 따라 바뀌는 분모(R² 분산, 개별 Range)는 Headline 금지.
2. **보고 지표와 최적화 Loss 분리** — CORA·S&G는 불연속점 때문에 Loss로 못 쓰고, 매끄러운 복합 L2로 수렴시킨 뒤 Headline으로 판정.
3. **원인 분해는 곱셈·분리형으로** — CORA 3축(Kp·Kv·Kg), S&G M/P, 3D Procrustes+Hausdorff 쌍. "왜 깎였는지"가 보여야 함.
