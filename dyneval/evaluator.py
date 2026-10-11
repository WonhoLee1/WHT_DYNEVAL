"""1D/3D 동역학 시계열 정합도 통합 평가 및 최적화 손실 엔진.

my_plan_dyneval.md의 최종 통합 클래스(ComprehensiveDynamicEvaluator)를
제품 코드로 정리한 모듈이다. 계획안 초안의 알려진 버그
(3D Frechet 폴백식 오류, 전구간 DTW 과부하)를 수정 반영했다.
"""

from __future__ import annotations

import numpy as np
from scipy import signal
from scipy.spatial.distance import cdist


def worst_axis_nrmse(y_exp: np.ndarray, y_sim: np.ndarray) -> float | None:
    """축별 자가폭 NRMSE 중 최솟값을 반환한다.

    정지축(폭이 전체 대각선의 1% 미만)은 제외해
    순수 1축 운동이 0점으로 오판되는 것을 막는다.
    유효 축이 하나도 없으면 None을 반환한다.

    Parameters
    ----------
    y_exp : np.ndarray
        (N, 3) 기준 궤적.
    y_sim : np.ndarray
        (N, 3) 해석 궤적.

    Returns
    -------
    float | None
        최악축 점수 또는 None.
    """
    e = np.asarray(y_exp, dtype=np.float64)
    s = np.asarray(y_sim, dtype=np.float64)
    ptp = np.ptp(e, axis=0)
    diag = max(float(np.linalg.norm(ptp)), 1e-9)
    active = ptp > 0.01 * diag
    if not bool(np.any(active)):
        return None
    rmse = np.sqrt(np.mean((e - s) ** 2, axis=0))
    return float(
        min(
            max(0.0, (1.0 - r / max(p, 1e-9)) * 100.0)
            for r, p, a in zip(rmse, ptp, active)
            if a
        )
    )


def total_dynamic_accuracy(
    time: np.ndarray,
    v_exp: np.ndarray,
    v_sim: np.ndarray,
    x_exp: np.ndarray,
    x_sim: np.ndarray,
    w_vel: float = 0.6,
) -> dict:
    """대표 단일 Headline(Total Dynamic Accuracy)을 계산한다.

    Total (%) = w_vel × S_vel + (1 − w_vel) × S_disp.
    1D는 S&G(v)+NRMSE(x), 3D는 Vector S&G(v)+ATE(r) 조합을 자동 선택한다.

    Parameters
    ----------
    time : np.ndarray
        시간 배열.
    v_exp : np.ndarray
        기준 속도 신호 ((N,) 또는 (N, 3)).
    v_sim : np.ndarray
        해석 속도 신호.
    x_exp : np.ndarray
        기준 변위 신호.
    x_sim : np.ndarray
        해석 변위 신호.
    w_vel : float
        속도 가중치 (기본 0.6, 충돌·진동 중심이면 0.7, 정적 중심이면 0.5).

    Returns
    -------
    dict
        Total(%), S_vel(%), S_disp(%), 가중치의 결과 딕셔너리.
    """
    s_vel = ComprehensiveDynamicEvaluator(time, v_exp, mode="vel").evaluate(v_sim)[
        "Main_Headline_Accuracy(%)"
    ]
    ev_disp = ComprehensiveDynamicEvaluator(time, x_exp, mode="disp")
    rep_disp = ev_disp.evaluate(x_sim)
    s_disp = rep_disp["Main_Headline_Accuracy(%)"]
    detail: dict = {"S_vel(%)": s_vel, "S_disp(%)": s_disp, "w_vel": w_vel}
    if ev_disp.is_3d:
        worst = worst_axis_nrmse(x_exp, x_sim)
        if worst is None:
            worst = float(s_disp)
        worst = round(worst, 1)
        s_disp = min(float(s_disp), worst)
        detail["S_disp_ATE(%)"] = rep_disp["Main_Headline_Accuracy(%)"]
        detail["WorstAxis(%)"] = worst
        detail["S_disp(%)"] = s_disp
    total = w_vel * float(s_vel) + (1.0 - w_vel) * float(s_disp)
    detail["Total(%)"] = round(total, 1)
    return detail


class ComprehensiveDynamicEvaluator:
    """1D/3D 시계열 데이터(변위, 속도) 통합 정합도 평가 및 최적화 엔진.

    ======================================================================
    [1D & 3D 동역학 시계열 정합도 평가 지표 및 최적화 연동 체계]
    ======================================================================
    | 차원     | 모드      | 주 평가지표 (Headline 100%)      | 기준 척도 (0% Base) |
    |----------|-----------|----------------------------------|---------------------|
    | 1D Scalar| 변위(disp)| Global NRMSE Score               | Peak-to-Peak 폭     |
    |          |           | max(0, 1 - RMSE/dx) * 100        | (xmax - xmin)       |
    | 1D Scalar| 속도(vel) | Sprague & Geers Score            | 1D 적분 에너지      |
    |          |           | max(0, 1 - C) * 100              | (∫v^2 dt)           |
    | 3D Vector| 변위(disp)| Spatial ATE Score                | Bounding Box 대각선 |
    |          |           | max(0, 1 - RMSE_3D/L_diag)*100   | L_diag=norm(dx,dy,dz)|
    | 3D Vector| 속도(vel) | Vector Sprague & Geers           | 3D 총 운동에너지    |
    |          |           | max(0, 1 - C_3D) * 100           | ∫(vx^2+vy^2+vz^2)dt |
    ======================================================================
    세부 진단 지표:
      - 1D 공통: MSE, RMSE, R2(NSE), Pearson Corr, DTW 거리/점수
      - 1D vel 추가: S&G 분해 M(크기)/P(위상)/C(종합),
        경량 CORA 3축 Kp(지연 ms)/Kv(형상)/Kg(면적·피크)
      - 3D 공통: Spatial RMSE(ATE), Hausdorff(최악 이탈),
        Frechet(기하 형상), Procrustes(순수 형상, 파라미터 프리)
    최적화 손실(calc_loss, 전구간 연속 미분 가능):
      - vel (1D/3D): 0.4 * L2 + 0.3 * 피크오차^2 + 0.3 * 면적오차^2
      - disp (1D/3D): 0.7 * L2 + 0.3 * 피크오차^2

    Parameters
    ----------
    time : np.ndarray
        (N,) 형태의 시간 배열 (단위: s, 단조 증가).
    y_exp : np.ndarray
        (N,) 형태의 1D 신호 또는 (N, 3) 형태의 3D 벡터 신호 (시험/기준).
    mode : str
        신호 유형 ("vel": 속도/충격량 중심, "disp": 위치/궤적 중심).
    ref_scale : float, optional
        사용자 정의 기준 스케일. None이면 데이터에서 자동 산출
        (1D: Peak-to-Peak 폭, 3D: Bounding Box 대각선 길이).
    tau_allow : float, optional
        CORA 시간 지연 평가 시 0%로 간주할 허용 최대 지연 (초).
        None이면 max(0.02, 전체시간*0.1).
    """

    #: DTW 계산 전 리샘플링 상한 (계산량 O(n^2) 억제용).
    _DTW_MAX_POINTS = 300
    #: Frechet 계산 전 리샘플링 상한.
    _FRECHET_MAX_POINTS = 100

    def __init__(
        self,
        time: np.ndarray,
        y_exp: np.ndarray,
        mode: str = "vel",
        ref_scale: float | None = None,
        tau_allow: float | None = None,
    ) -> None:
        self.t = np.asarray(time, dtype=np.float64)
        self.y_exp = np.asarray(y_exp, dtype=np.float64)
        self.mode = mode.lower()
        if self.mode not in ("vel", "disp"):
            raise ValueError("mode는 'vel' 또는 'disp'이어야 합니다.")
        if self.t.ndim != 1 or len(self.t) < 4:
            raise ValueError("time은 길이가 4 이상인 1D 배열이어야 합니다.")
        if not np.all(np.diff(self.t) > 0):
            raise ValueError("time은 단조 증가해야 합니다.")
        self.dt = np.gradient(self.t)
        self.N = len(self.t)

        if self.y_exp.ndim == 1 or (
            self.y_exp.ndim == 2 and self.y_exp.shape[1] == 1
        ):
            self.is_3d = False
            self.y_exp = self.y_exp.flatten()
        elif self.y_exp.ndim == 2 and self.y_exp.shape[1] == 3:
            self.is_3d = True
        else:
            raise ValueError(
                "y_exp는 (N,) 형태의 1D 신호이거나 (N, 3) 형태의 3D 신호여야 합니다."
            )
        if self.y_exp.shape[0] != self.N:
            raise ValueError("y_exp의 시간 스텝 수가 time과 일치해야 합니다.")

        if ref_scale is not None:
            self.ref_scale = float(ref_scale)
            self.ptp_per_axis = (
                np.ptp(self.y_exp, axis=0)
                if self.is_3d
                else float(np.ptp(self.y_exp))
            )
        else:
            if not self.is_3d:
                self.ptp_per_axis = float(np.ptp(self.y_exp))
                self.ref_scale = max(self.ptp_per_axis, 1e-9)
            else:
                self.ptp_per_axis = np.ptp(self.y_exp, axis=0)
                self.ref_scale = float(np.linalg.norm(self.ptp_per_axis))
                if self.ref_scale < 1e-9:
                    self.ref_scale = 1.0
        if self.ref_scale < 1e-9:
            self.ref_scale = 1.0

        total_time = float(self.t[-1] - self.t[0])
        self.tau_allow = (
            tau_allow
            if tau_allow is not None
            else max(0.02, total_time * 0.1)
        )

    # ------------------------------------------------------------------
    # 내부 유틸
    # ------------------------------------------------------------------
    def _as_sim(self, y_sim: np.ndarray) -> np.ndarray:
        """해석 신호를 기준 차원에 맞춰 정규화한 배열로 반환한다.

        Parameters
        ----------
        y_sim : np.ndarray
            해석/시뮬레이션 신호.

        Returns
        -------
        np.ndarray
            1D면 (N,), 3D면 (N, 3) 배열.
        """
        arr = np.asarray(y_sim, dtype=np.float64)
        if not self.is_3d:
            arr = arr.flatten()
            if arr.shape[0] != self.N:
                raise ValueError("y_sim 길이가 기준 신호와 다릅니다.")
        else:
            if arr.shape != (self.N, 3):
                raise ValueError("3D 모드에서 y_sim은 (N, 3)이어야 합니다.")
        return arr

    @staticmethod
    def _stride_for(n: int, limit: int) -> int:
        """길이 n을 limit 이하로 줄이는 균일 솎음 간격을 구한다."""
        return max(1, (n + limit - 1) // limit)

    # ------------------------------------------------------------------
    # 1D 통계 지표
    # ------------------------------------------------------------------
    def calc_1d_statistical(self, y_sim: np.ndarray) -> dict:
        """MSE, RMSE, R2(NSE), Pearson 상관계수를 계산한다.

        Parameters
        ----------
        y_sim : np.ndarray
            (N,) 해석 신호.

        Returns
        -------
        dict
            MSE/RMSE/R2/Pearson_Corr 값.
        """
        s = self._as_sim(y_sim)
        mse = float(np.mean((self.y_exp - s) ** 2))
        rmse = float(np.sqrt(mse))
        ss_res = float(np.sum((self.y_exp - s) ** 2))
        ss_tot = float(np.sum((self.y_exp - np.mean(self.y_exp)) ** 2))
        r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-12 else 0.0
        std_e, std_s = float(np.std(self.y_exp)), float(np.std(s))
        if std_e > 1e-9 and std_s > 1e-9:
            corr = float(np.corrcoef(self.y_exp, s)[0, 1])
        else:
            corr = 0.0
        return {"MSE": mse, "RMSE": rmse, "R2": r2, "Pearson_Corr": corr}

    @staticmethod
    def _dtw_mean_distance(a: np.ndarray, b: np.ndarray) -> float:
        """두 1D 배열의 DTW 점별 평균 누적 거리를 반환한다.

        Parameters
        ----------
        a : np.ndarray
            기준 신호.
        b : np.ndarray
            해석 신호.

        Returns
        -------
        float
            점별 평균 DTW 거리.
        """
        n, m = len(a), len(b)
        prev = np.full(m + 1, np.inf)
        prev[0] = 0.0
        for i in range(1, n + 1):
            curr = np.full(m + 1, np.inf)
            ai = a[i - 1]
            for j in range(1, m + 1):
                cost = abs(ai - b[j - 1])
                best = prev[j]
                if curr[j - 1] < best:
                    best = curr[j - 1]
                if prev[j - 1] < best:
                    best = prev[j - 1]
                curr[j] = cost + best
            prev = curr
        return float(prev[m] / n)

    def calc_1d_dtw(self, y_sim: np.ndarray) -> dict:
        """1D DTW 점별 평균 누적 거리와 100점 환산 점수를 계산한다.

        Parameters
        ----------
        y_sim : np.ndarray
            (N,) 해석 신호.

        Returns
        -------
        dict
            DTW_Distance, DTW_Score(%).
        """
        s = self._as_sim(y_sim)
        stride = self._stride_for(self.N, self._DTW_MAX_POINTS)
        dtw_dist = self._dtw_mean_distance(self.y_exp[::stride], s[::stride])
        dtw_score = max(0.0, (1.0 - dtw_dist / self.ref_scale) * 100.0)
        return {"DTW_Distance": dtw_dist, "DTW_Score(%)": round(dtw_score, 1)}

    def calc_1d_cora_light(self, y_sim: np.ndarray) -> dict:
        """경량 CORA 3축 분해 (지연 Kp / 형상 Kv / 크기 Kg)를 계산한다.

        Parameters
        ----------
        y_sim : np.ndarray
            (N,) 해석 신호.

        Returns
        -------
        dict
            CORA_Score(%), Delay_Score_Kp, Time_Delay_ms,
            Shape_Score_Kv, Magnitude_Score_Kg.
        """
        s = self._as_sim(y_sim)
        dt = float(np.mean(self.dt))
        corr = signal.correlate(
            s - np.mean(s), self.y_exp - np.mean(self.y_exp), mode="full"
        )
        lags = signal.correlation_lags(self.N, self.N, mode="full") * dt
        best_lag = float(lags[int(np.argmax(corr))])
        k_p = max(0.0, 1.0 - abs(best_lag) / self.tau_allow)

        shift_steps = int(round(best_lag / dt))
        if shift_steps > 0:
            s_shifted = np.pad(s, (0, shift_steps), mode="edge")[shift_steps:]
        elif shift_steps < 0:
            s_shifted = np.pad(s, (-shift_steps, 0), mode="edge")[:shift_steps]
        else:
            s_shifted = s.copy()
        std_e, std_s = float(np.std(self.y_exp)), float(np.std(s_shifted))
        if std_e > 1e-9 and std_s > 1e-9:
            k_v = max(0.0, float(np.corrcoef(self.y_exp, s_shifted)[0, 1]))
        else:
            k_v = 0.0

        peak_e = float(np.max(np.abs(self.y_exp)))
        peak_s = float(np.max(np.abs(s)))
        s_peak = max(
            0.0, 1.0 - abs(peak_e - peak_s) / max(peak_e, peak_s, 1e-9)
        )
        area_e = float(np.sum(np.abs(self.y_exp) * self.dt)) + 1e-9
        area_s = float(np.sum(np.abs(s) * self.dt)) + 1e-9
        s_area = min(area_s / area_e, area_e / area_s)
        k_g = 0.5 * s_peak + 0.5 * s_area
        cora_score = (k_p * k_v * k_g) * 100.0
        return {
            "CORA_Score(%)": round(cora_score, 1),
            "Delay_Score_Kp": round(k_p, 4),
            "Time_Delay_ms": round(best_lag * 1000.0, 2),
            "Shape_Score_Kv": round(k_v, 4),
            "Magnitude_Score_Kg": round(k_g, 4),
        }

    # ------------------------------------------------------------------
    # 3D 궤적 지표
    # ------------------------------------------------------------------
    def _resample_3d(self, r_sim: np.ndarray, limit: int) -> tuple:
        """3D 궤적 쌍을 계산량 제한 이하로 균일 솎음한다."""
        stride = self._stride_for(self.N, limit)
        return self.y_exp[::stride], np.asarray(r_sim)[::stride]

    def calc_3d_frechet(self, r_sim: np.ndarray) -> dict:
        """이산 Frechet 거리와 100점 환산 점수를 계산한다 (반복 DP).

        Parameters
        ----------
        r_sim : np.ndarray
            (N, 3) 해석 궤적.

        Returns
        -------
        dict
            Frechet_Dist(m), Frechet_Score(%).
        """
        s = self._as_sim(r_sim)
        p, q = self._resample_3d(s, self._FRECHET_MAX_POINTS)
        n, m = len(p), len(q)
        ca = np.full((n, m), np.inf)
        for i in range(n):
            for j in range(m):
                d = float(np.linalg.norm(p[i] - q[j]))
                if i == 0 and j == 0:
                    ca[i, j] = d
                elif i > 0 and j == 0:
                    ca[i, j] = max(ca[i - 1, 0], d)
                elif i == 0 and j > 0:
                    ca[i, j] = max(ca[0, j - 1], d)
                else:
                    ca[i, j] = max(
                        min(ca[i - 1, j], ca[i - 1, j - 1], ca[i, j - 1]), d
                    )
        d_f = float(ca[n - 1, m - 1])
        score = max(0.0, (1.0 - d_f / self.ref_scale) * 100.0)
        return {"Frechet_Dist(m)": round(d_f, 5), "Frechet_Score(%)": round(score, 1)}

    def calc_3d_procrustes(self, r_sim: np.ndarray) -> dict:
        """SVD 강체 정렬 후 순수 형상 잔차(Procrustes)를 계산한다.

        Parameters
        ----------
        r_sim : np.ndarray
            (N, 3) 해석 궤적.

        Returns
        -------
        dict
            Procrustes_Disparity, Procrustes_Score(%).
        """
        s = self._as_sim(r_sim)
        x_mat = self.y_exp - np.mean(self.y_exp, axis=0)
        y_mat = s - np.mean(s, axis=0)
        norm_x = float(np.sqrt(np.sum(x_mat**2)))
        norm_y = float(np.sqrt(np.sum(y_mat**2)))
        if norm_x < 1e-12 or norm_y < 1e-12:
            return {"Procrustes_Disparity": 1.0, "Procrustes_Score(%)": 0.0}
        x_mat = x_mat / norm_x
        y_mat = y_mat / norm_y
        h_mat = np.dot(y_mat.T, x_mat)
        u_mat, s_vals, vt_mat = np.linalg.svd(h_mat)
        if float(np.linalg.det(np.dot(u_mat, vt_mat))) < 0:
            vt_mat[-1, :] *= -1
            s_vals[-1] *= -1
        disparity = max(0.0, 1.0 - float(np.sum(s_vals)) ** 2)
        score = max(0.0, (1.0 - np.sqrt(disparity)) * 100.0)
        return {
            "Procrustes_Disparity": round(disparity, 5),
            "Procrustes_Score(%)": round(score, 1),
        }

    def calc_3d_hausdorff(self, r_sim: np.ndarray) -> dict:
        """Hausdorff 최악 이탈 거리와 100점 환산 점수를 계산한다.

        Parameters
        ----------
        r_sim : np.ndarray
            (N, 3) 해석 궤적.

        Returns
        -------
        dict
            Hausdorff_Dist(m), Hausdorff_Score(%).
        """
        s = self._as_sim(r_sim)
        stride = self._stride_for(self.N, 400)
        dists = cdist(self.y_exp[::stride], s[::stride])
        d_h = float(
            max(np.max(np.min(dists, axis=1)), np.max(np.min(dists, axis=0)))
        )
        score = max(0.0, (1.0 - d_h / self.ref_scale) * 100.0)
        return {
            "Hausdorff_Dist(m)": round(d_h, 5),
            "Hausdorff_Score(%)": round(score, 1),
        }

    def calc_3d_axis_metrics(self, r_sim: np.ndarray) -> dict:
        """3D 축별(x/y/z) 1D 지표 부록을 계산한다.

        R²·Corr 같은 상대치 지표는 축 분산 크기에 따라 같은 오차도
        다르게 보이므로, 축별 분산 점유율과 지배/미세 판정을 함께 반환해
        오독을 방지한다.

        Parameters
        ----------
        r_sim : np.ndarray
            (N, 3) 해석 궤적.

        Returns
        -------
        dict
            축별 RMSE/R2/Corr/DTW_Score/분산점유율/판정 딕셔너리.
        """
        s = self._as_sim(r_sim)
        var = np.var(self.y_exp, axis=0)
        share = var / max(float(np.sum(var)), 1e-12)
        stride = self._stride_for(self.N, self._DTW_MAX_POINTS)
        axes = {}
        for k, name in enumerate(("x", "y", "z")):
            e = self.y_exp[:, k]
            q = s[:, k]
            rmse = float(np.sqrt(np.mean((e - q) ** 2)))
            ss_res = float(np.sum((e - q) ** 2))
            ss_tot = float(np.sum((e - np.mean(e)) ** 2))
            r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-12 else 0.0
            if float(np.std(e)) > 1e-9 and float(np.std(q)) > 1e-9:
                corr = float(np.corrcoef(e, q)[0, 1])
            else:
                corr = 0.0
            span = max(float(np.ptp(e)), 1e-9)
            dtw_d = self._dtw_mean_distance(e[::stride], q[::stride])
            dtw_s = max(0.0, (1.0 - dtw_d / span) * 100.0)
            axes[name] = {
                "RMSE": round(rmse, 5),
                "R2": round(r2, 3),
                "Corr": round(corr, 3),
                "DTW_Score(%)": round(dtw_s, 1),
                "Var_Share": round(float(share[k]), 3),
                "판정": "지배축" if share[k] > 0.2 else "미세축(상대치 주의)",
            }
        return axes

    # ------------------------------------------------------------------
    # Sprague & Geers (1D/3D 공통 코어)
    # ------------------------------------------------------------------
    def calc_sprague_geers(self, y_sim: np.ndarray) -> dict:
        """Sprague & Geers M(크기)/P(위상)/C(종합)와 100점 점수를 계산한다.

        Parameters
        ----------
        y_sim : np.ndarray
            (N,) 또는 (N, 3) 해석 신호.

        Returns
        -------
        dict
            M, P, C, Score(%).
        """
        s = self._as_sim(y_sim)
        if not self.is_3d:
            i_ee = float(np.sum(self.y_exp**2 * self.dt))
            i_ss = float(np.sum(s**2 * self.dt))
            i_es = float(np.sum(self.y_exp * s * self.dt))
        else:
            i_ee = float(np.sum(np.sum(self.y_exp * self.y_exp, axis=1) * self.dt))
            i_ss = float(np.sum(np.sum(s * s, axis=1) * self.dt))
            i_es = float(np.sum(np.sum(self.y_exp * s, axis=1) * self.dt))
        eps = 1e-12
        i_ee = max(i_ee, eps)
        i_ss = max(i_ss, eps)
        m_val = float(np.sqrt(i_ss / i_ee) - 1.0)
        cos_val = float(np.clip(i_es / np.sqrt(i_ee * i_ss), -1.0, 1.0))
        p_val = float((1.0 / np.pi) * np.arccos(cos_val))
        c_val = float(np.sqrt(m_val**2 + p_val**2))
        score = max(0.0, (1.0 - c_val) * 100.0)
        return {"M": m_val, "P": p_val, "C": c_val, "Score(%)": score}

    # ------------------------------------------------------------------
    # 종합 보고서
    # ------------------------------------------------------------------
    def evaluate(self, y_sim: np.ndarray) -> dict:
        """차원·모드에 맞는 100% 만점 체계 정합도 보고서를 생성한다.

        Parameters
        ----------
        y_sim : np.ndarray
            해석 신호 ((N,) 또는 (N, 3)).

        Returns
        -------
        dict
            Headline 정확도 및 세부 지표 딕셔너리.
        """
        s = self._as_sim(y_sim)
        report: dict = {
            "Dimension": "3D Vector" if self.is_3d else "1D Scalar",
            "Mode": "Velocity" if self.mode == "vel" else "Displacement",
            "Reference_Scale": round(self.ref_scale, 4),
        }
        if not self.is_3d:
            stats = self.calc_1d_statistical(s)
            dtw = self.calc_1d_dtw(s)
            cora = self.calc_1d_cora_light(s)
            sg = self.calc_sprague_geers(s)
            nrmse_score = max(0.0, (1.0 - stats["RMSE"] / self.ref_scale) * 100.0)
            if self.mode == "vel":
                report["Main_Headline_Accuracy(%)"] = round(sg["Score(%)"], 1)
                report["Sprague_Geers"] = {
                    "M": round(sg["M"], 4),
                    "P": round(sg["P"], 4),
                    "C": round(sg["C"], 4),
                }
                report["CORA_Light_Decomposition"] = cora
            else:
                report["Main_Headline_Accuracy(%)"] = round(nrmse_score, 1)
                report["Global_NRMSE_Score(%)"] = round(nrmse_score, 1)
                tail = max(1, int(self.N * 0.1))
                res_err = abs(float(np.mean(self.y_exp[-tail:])) - float(np.mean(s[-tail:])))
                report["Residual_Disp_Error(m)"] = round(res_err, 5)
            report["Statistical_Metrics"] = {
                "RMSE": round(stats["RMSE"], 5),
                "R2": round(stats["R2"], 4),
                "Pearson_Corr": round(stats["Pearson_Corr"], 4),
            }
            report["DTW"] = dtw
        else:
            sg_3d = self.calc_sprague_geers(s)
            frechet = self.calc_3d_frechet(s)
            procrustes = self.calc_3d_procrustes(s)
            hausdorff = self.calc_3d_hausdorff(s)
            diff = self.y_exp - s
            spatial_rmse = float(np.sqrt(np.mean(np.sum(diff**2, axis=1))))
            ate_score = max(0.0, (1.0 - spatial_rmse / self.ref_scale) * 100.0)
            if self.mode == "vel":
                report["Main_Headline_Accuracy(%)"] = round(sg_3d["Score(%)"], 1)
                report["Vector_Sprague_Geers"] = {
                    "M_Energy": round(sg_3d["M"], 4),
                    "P_Phase_Orientation": round(sg_3d["P"], 4),
                    "C_Combined": round(sg_3d["C"], 4),
                }
            else:
                report["Main_Headline_Accuracy(%)"] = round(ate_score, 1)
                report["Spatial_ATE_Score(%)"] = round(ate_score, 1)
                worst = worst_axis_nrmse(self.y_exp, s)
                report["Worst_Axis_NRMSE_Score(%)"] = (
                    round(worst, 1) if worst is not None else round(ate_score, 1)
                )
            report["3D_Trajectory_Metrics"] = {
                "Spatial_RMSE_ATE(m)": round(spatial_rmse, 5),
                "Bounding_Box_Diag_Lref(m)": round(self.ref_scale, 4),
                "Hausdorff": hausdorff,
                "Frechet": frechet,
                "Procrustes_Pure_Shape": procrustes,
            }
            report["Axis_Metrics"] = self.calc_3d_axis_metrics(s)
        return report

    # ------------------------------------------------------------------
    # 최적화 손실
    # ------------------------------------------------------------------
    def calc_loss(self, y_sim: np.ndarray) -> float:
        """구배 기반 탐색기용 전구간 연속 미분 가능 무차원 손실을 반환한다.

        불연속 연산(argmax, max 클리핑)을 배제하고 L2·피크·면적 항만
        사용하므로 CORA/S&G와 달리 최적화 루프에 직접 넣어도 안정적이다.

        Parameters
        ----------
        y_sim : np.ndarray
            해석 신호 ((N,) 또는 (N, 3)).

        Returns
        -------
        float
            무차원 복합 손실값 (0 = 완전 일치).
        """
        s = self._as_sim(y_sim)
        if not self.is_3d:
            if self.mode == "vel":
                p_exp = float(np.max(np.abs(self.y_exp)))
                p_sim = float(np.max(np.abs(s)))
                loss_peak = ((p_exp - p_sim) / (p_exp + 1e-6)) ** 2
                a_exp = float(np.sum(np.abs(self.y_exp) * self.dt))
                a_sim = float(np.sum(np.abs(s) * self.dt))
                loss_area = ((a_exp - a_sim) / (a_exp + 1e-6)) ** 2
                loss_l2 = float(np.sum((self.y_exp - s) ** 2) / (np.sum(self.y_exp**2) + 1e-6))
                return 0.3 * loss_peak + 0.3 * loss_area + 0.4 * loss_l2
            loss_l2 = float(np.mean((self.y_exp - s) ** 2) / (self.ref_scale**2 + 1e-6))
            loss_peak = float(((np.max(self.y_exp) - np.max(s)) / self.ref_scale) ** 2)
            return 0.7 * loss_l2 + 0.3 * loss_peak
        if self.mode == "vel":
            p_exp = float(np.max(np.linalg.norm(self.y_exp, axis=1)))
            p_sim = float(np.max(np.linalg.norm(s, axis=1)))
            loss_peak = ((p_exp - p_sim) / (p_exp + 1e-6)) ** 2
            a_exp = float(np.sum(np.linalg.norm(self.y_exp, axis=1) * self.dt))
            a_sim = float(np.sum(np.linalg.norm(s, axis=1) * self.dt))
            loss_area = ((a_exp - a_sim) / (a_exp + 1e-6)) ** 2
            loss_l2 = float(np.sum((self.y_exp - s) ** 2) / (np.sum(self.y_exp**2) + 1e-6))
            return 0.3 * loss_peak + 0.3 * loss_area + 0.4 * loss_l2
        loss_l2 = float(
            np.mean(np.sum((self.y_exp - s) ** 2, axis=1)) / (self.ref_scale**2 + 1e-6)
        )
        p_exp = float(np.max(np.linalg.norm(self.y_exp, axis=1)))
        p_sim = float(np.max(np.linalg.norm(s, axis=1)))
        loss_peak = ((p_exp - p_sim) / (self.ref_scale + 1e-6)) ** 2
        return 0.7 * loss_l2 + 0.3 * loss_peak
