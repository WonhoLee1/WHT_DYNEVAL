"""ComprehensiveDynamicEvaluator 연동 파라미터 최적화 래퍼."""

from __future__ import annotations

from typing import Any, Callable
import numpy as np
from scipy.optimize import minimize

try:
    from dyneval.evaluator import ComprehensiveDynamicEvaluator
except ImportError:  # 패키지 상대 import 폴백
    from .evaluator import ComprehensiveDynamicEvaluator


def optimize_dynamic_parameters(
    sim_func: Callable[[np.ndarray, np.ndarray], np.ndarray],
    init_params: np.ndarray,
    time: np.ndarray,
    y_exp: np.ndarray,
    mode: str = "vel",
    bounds: list | None = None,
    method: str = "L-BFGS-B",
    ref_scale: float | None = None,
    options: dict | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    """시뮬레이션 파라미터를 보정하고 전/후 100% 보고서를 함께 반환한다.

    최적화 루프 안에서는 불연속점이 없는 매끄러운 ``calc_loss``만
    최소화하고, 최종 판정은 100% 만점 ``evaluate`` 보고서로 수행하는
    2단계(수렴 보장형 Loss + 공학 보고 Score) 파이프라인이다.

    Parameters
    ----------
    sim_func : Callable
        ``y_sim = sim_func(params, time)`` 형태의 수치해석 함수.
    init_params : np.ndarray
        최적화 시작 파라미터 초기 추정치.
    time : np.ndarray
        시간 배열.
    y_exp : np.ndarray
        실험/목표 데이터 ((N,) 또는 (N, 3)).
    mode : str
        "vel" 또는 "disp".
    bounds : list, optional
        파라미터 탐색 상/하한 [(min, max), ...].
    method : str
        SciPy minimize 알고리즘명.
    ref_scale : float, optional
        물리적 기준 척도 (None이면 자동 산출).
    options : dict, optional
        SciPy 세부 옵션 (기본 {'maxiter': 150}).
    verbose : bool
        진행 상황 출력 여부.

    Returns
    -------
    dict
        optimal_params, success, iterations, initial/final_loss,
        initial/calibrated_accuracy(%), initial/calibrated_report,
        y_sim_calibrated, evaluator, history 키의 결과 딕셔너리.
    """
    evaluator = ComprehensiveDynamicEvaluator(
        time=time, y_exp=y_exp, mode=mode, ref_scale=ref_scale
    )
    init_p = np.asarray(init_params, dtype=np.float64)
    history: list[float] = []

    def objective_wrapper(params: np.ndarray) -> float:
        """솔버 발산 방어 래퍼 (예외·NaN/Inf·형상 불일치 → 1e6 페널티)."""
        try:
            y_sim = np.asarray(sim_func(params, time), dtype=np.float64)
            if y_sim.shape != np.asarray(y_exp).shape:
                if y_sim.flatten().shape != np.asarray(y_exp).flatten().shape:
                    return 1e6
            loss = float(evaluator.calc_loss(y_sim))
            if not np.isfinite(loss):
                return 1e6
        except Exception:
            return 1e6
        history.append(loss)
        return loss

    y_sim_init = np.asarray(sim_func(init_p, time), dtype=np.float64)
    init_report = evaluator.evaluate(y_sim_init)
    init_loss = objective_wrapper(init_p)
    if verbose:
        print("==================================================")
        print(
            f"[동역학 파라미터 최적화 시작] Mode: {mode.upper()} | "
            f"Dim: {'3D' if evaluator.is_3d else '1D'}"
        )
        print(f"  초기 파라미터: {init_p}")
        print(f"  초기 손실값(Loss): {init_loss:.6e}")
        print(f"  초기 Headline 정합도: {init_report['Main_Headline_Accuracy(%)']:.1f}%")
        print("--------------------------------------------------")

    opt_options = options if options is not None else {"maxiter": 150}
    res = minimize(
        fun=objective_wrapper,
        x0=init_p,
        method=method,
        bounds=bounds,
        options=opt_options,
    )
    opt_params = res.x
    y_sim_opt = np.asarray(sim_func(opt_params, time), dtype=np.float64)
    final_report = evaluator.evaluate(y_sim_opt)
    init_score = float(init_report["Main_Headline_Accuracy(%)"])
    final_score = float(final_report["Main_Headline_Accuracy(%)"])
    if verbose:
        print(f"[최적화 완료] 수렴 성공 여부: {res.success} ({res.message})")
        print(f"  반복 횟수: {res.nit}회 (목적함수 호출 {res.nfev}회)")
        print(f"  최적 파라미터: {np.round(opt_params, 5)}")
        print(
            f"  최종 손실값(Loss): {res.fun:.6e} "
            f"(감소율: {(1.0 - res.fun / max(init_loss, 1e-12)) * 100:.1f}%)"
        )
        print(f"  >> 정합도 개선: {init_score:.1f}% → {final_score:.1f}% "
              f"(+{final_score - init_score:.1f}%p)")
        print("==================================================")
    return {
        "optimal_params": opt_params,
        "success": res.success,
        "message": res.message,
        "iterations": res.nit,
        "initial_loss": init_loss,
        "final_loss": float(res.fun),
        "initial_accuracy(%)": init_score,
        "calibrated_accuracy(%)": final_score,
        "initial_report": init_report,
        "calibrated_report": final_report,
        "y_sim_calibrated": y_sim_opt,
        "evaluator": evaluator,
        "history": history,
    }
