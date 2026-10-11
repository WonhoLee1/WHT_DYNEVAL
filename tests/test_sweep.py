"""지표 스위프 스모크 테스트.

동일 신호 100% / 위상·크기 악화 시 감점 / 예외 검증을 분리 함수로 수행하며,
사용 예시는 main 블록에 둔다.
"""

from __future__ import annotations

import numpy as np
import pytest

from dyneval import ComprehensiveDynamicEvaluator
from dyneval.optimize import optimize_dynamic_parameters
from dyneval.signals import make_1d_drop_signals, make_3d_trajectory_signals


def test_identical_signals_score_100() -> None:
    """동일 신호 입력 시 4개 조합 모두 Headline 100%, loss 0이어야 한다."""
    t = np.linspace(0, 1.5, 200)
    s1 = make_1d_drop_signals(t)
    assert ComprehensiveDynamicEvaluator(t, s1["vel_exp"], mode="vel").evaluate(
        s1["vel_exp"]
    )["Main_Headline_Accuracy(%)"] == 100.0
    assert ComprehensiveDynamicEvaluator(t, s1["disp_exp"], mode="disp").evaluate(
        s1["disp_exp"]
    )["Main_Headline_Accuracy(%)"] == 100.0
    g = make_3d_trajectory_signals(t)
    assert ComprehensiveDynamicEvaluator(t, g["vel_exp"], mode="vel").evaluate(
        g["vel_exp"]
    )["Main_Headline_Accuracy(%)"] == 100.0
    assert ComprehensiveDynamicEvaluator(t, g["disp_exp"], mode="disp").evaluate(
        g["disp_exp"]
    )["Main_Headline_Accuracy(%)"] == 100.0
    ev = ComprehensiveDynamicEvaluator(t, s1["vel_exp"], mode="vel")
    assert ev.calc_loss(s1["vel_exp"]) == 0.0


def test_phase_delay_degrades_score() -> None:
    """위상 지연이 커지면 1D 속도 S&G 점수가 단조 감소해야 한다."""
    t = np.linspace(0, 1.5, 300)
    base = make_1d_drop_signals(t)
    ev = ComprehensiveDynamicEvaluator(t, base["vel_exp"], mode="vel")
    scores = []
    for delay in (0.0, 0.02, 0.06):
        sim = make_1d_drop_signals(t, delay=delay)["vel_sim"]
        scores.append(ev.evaluate(sim)["Main_Headline_Accuracy(%)"])
    assert scores[0] > scores[1] > scores[2]


def test_magnitude_error_hits_sg_m() -> None:
    """크기 오차는 S&G M항을 키우고 P항은 작게 유지해야 한다."""
    t = np.linspace(0, 1.5, 300)
    base = make_1d_drop_signals(t)
    ev = ComprehensiveDynamicEvaluator(t, base["vel_exp"], mode="vel")
    rep = ev.evaluate(make_1d_drop_signals(t, mag=1.25)["vel_sim"])
    assert abs(rep["Sprague_Geers"]["M"]) > 0.1
    assert rep["Sprague_Geers"]["P"] < 0.1


def test_corr_blind_to_magnitude() -> None:
    """상관계수는 순수 스케일 오차에 둔감함을 보여준다 (맹점 문서화)."""
    t = np.linspace(0, 1.5, 300)
    base = make_1d_drop_signals(t)
    ev = ComprehensiveDynamicEvaluator(t, base["vel_exp"], mode="vel")
    rep = ev.evaluate(make_1d_drop_signals(t, mag=1.25)["vel_sim"])
    assert rep["Statistical_Metrics"]["Pearson_Corr"] > 0.95
    assert rep["Main_Headline_Accuracy(%)"] < 95.0


def test_disp_headline_sg_option() -> None:
    """변위 모드에서 headline='sg' 지정 시 S&G 점수가 Headline이 되어야 한다."""
    t = np.linspace(0, 1.5, 300)
    base = make_1d_drop_signals(t)
    sim = make_1d_drop_signals(t, mag=1.25)["disp_sim"]
    rep_n = ComprehensiveDynamicEvaluator(t, base["disp_exp"], mode="disp").evaluate(sim)
    rep_s = ComprehensiveDynamicEvaluator(
        t, base["disp_exp"], mode="disp", headline="sg").evaluate(sim)
    assert rep_s["Headline_Func"] == "sg"
    assert rep_n["Headline_Func"] == "nrmse"
    assert rep_s["Main_Headline_Accuracy(%)"] == pytest.approx(75.0, abs=0.1)
    assert rep_n["Main_Headline_Accuracy(%)"] == pytest.approx(89.8, abs=0.1)
    with pytest.raises(ValueError):
        ComprehensiveDynamicEvaluator(t, base["disp_exp"], mode="disp", headline="xx")


def test_invalid_inputs_raise() -> None:
    """잘못된 mode/차원/시간 입력은 ValueError를 발생시켜야 한다."""
    t = np.linspace(0, 1.0, 50)
    y = np.sin(t)
    with pytest.raises(ValueError):
        ComprehensiveDynamicEvaluator(t, y, mode="acc")
    with pytest.raises(ValueError):
        ComprehensiveDynamicEvaluator(t, np.zeros((50, 2)), mode="vel")
    with pytest.raises(ValueError):
        ComprehensiveDynamicEvaluator(t[::-1], y, mode="vel")


def test_different_sampling_aligns_to_sparse() -> None:
    """샘플링이 달라도 성긴 쪽 격자로 보간 정렬되어 평가되어야 한다."""
    t_exp = np.linspace(0, 1.5, 400)
    t_sim = np.linspace(0, 1.5, 250)
    base_e = make_1d_drop_signals(t_exp)
    base_s = make_1d_drop_signals(t_sim)
    ev = ComprehensiveDynamicEvaluator(t_exp, base_e["vel_exp"], mode="vel")
    rep = ev.evaluate(base_s["vel_sim"], t_sim=t_sim)
    # 동일 물리라도 격자가 다르면 선형보간 고유 오차(P≈0.08)가 남는다
    assert rep["Main_Headline_Accuracy(%)"] > 85.0
    assert ev.calc_loss(base_s["vel_sim"], t_sim=t_sim) < 0.05
    with pytest.raises(ValueError):
        ev.evaluate(base_s["vel_sim"][:100], t_sim=t_sim)


def test_optimizer_reduces_loss() -> None:
    """토이 모델 최적화에서 최종 손실이 초기 손실 이하여야 한다."""
    t = np.linspace(0, 1.5, 200)
    base = make_1d_drop_signals(t)

    def toy_sim(params: np.ndarray, tt: np.ndarray) -> np.ndarray:
        """스케일·지연 2파라미터 토이 속도 모델."""
        scale, dly = params
        ts = np.maximum(0.0, tt - dly)
        return -9.81 * scale * np.clip(ts, 0, 0.45)

    out = optimize_dynamic_parameters(
        sim_func=toy_sim,
        init_params=np.array([0.7, 0.05]),
        time=t,
        y_exp=base["vel_exp"],
        mode="vel",
        bounds=[(0.5, 1.5), (-0.05, 0.1)],
        options={"maxiter": 15},
        verbose=False,
    )
    assert out["final_loss"] <= out["initial_loss"]


if __name__ == "__main__":
    test_identical_signals_score_100()
    print("identical 100% 확인")
    test_phase_delay_degrades_score()
    print("위상 감점 단조성 확인")
    test_magnitude_error_hits_sg_m()
    print("M/P 분리 확인")
    test_corr_blind_to_magnitude()
    print("Corr 맹점 확인")
    test_disp_headline_sg_option()
    print("변위 S&G Headline 옵션 확인")
    test_optimizer_reduces_loss()
    print("최적화 손실 감소 확인")
