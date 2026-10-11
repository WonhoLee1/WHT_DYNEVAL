"""평가 지표 스위프용 임의 기준/시뮬레이션 신호 생성기.

위상(delay), 크기(mag), 형태(shape) 노브를 독립 조절해
동일 물리에서 빗나간 해석 신호를 합성한다. 모든 생성은 seed 고정 난수로
재현 가능하며, 변위·속도 쌍을 함께 반환한다.
"""

from __future__ import annotations

import numpy as np


def _check_time(t: np.ndarray) -> np.ndarray:
    """시간 배열 단조 증가를 검증하고 float64 배열로 반환한다.

    Parameters
    ----------
    t : np.ndarray
        시간 배열.

    Returns
    -------
    np.ndarray
        검증된 시간 배열.
    """
    arr = np.asarray(t, dtype=np.float64)
    if arr.ndim != 1 or len(arr) < 4 or not np.all(np.diff(arr) > 0):
        raise ValueError("t는 단조 증가하는 길이 4 이상의 1D 배열이어야 합니다.")
    return arr


def _drop_profile(
    t: np.ndarray,
    h0: float = 1.0,
    g: float = 9.81,
    omega: float = 25.0,
    tau: float = 0.35,
    e_rebound: float = 0.6,
) -> tuple[np.ndarray, np.ndarray]:
    """자유낙하+감쇠 바운싱 변위/속도 프로파일을 합성한다.

    Parameters
    ----------
    t : np.ndarray
        시간 배열 (0 시작 가정).
    h0 : float
        초기 높이 (m).
    g : float
        중력가속도.
    omega : float
        바운싱 각주파수 (형태 노브).
    tau : float
        감쇠 시정수 (형태 노브).
    e_rebound : float
        반발 계수.

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        (변위, 속도) 배열.
    """
    t_impact = float(np.sqrt(2.0 * h0 / g))
    v_impact = float(np.sqrt(2.0 * g * h0))
    disp = np.zeros_like(t)
    vel = np.zeros_like(t)
    pre = t <= t_impact
    disp[pre] = h0 - 0.5 * g * t[pre] ** 2
    vel[pre] = -g * t[pre]
    post = ~pre
    dt_post = t[post] - t_impact
    decay = np.exp(-dt_post / tau)
    disp[post] = (h0 * 0.3) * np.abs(np.sin(omega * dt_post)) * decay
    vel[post] = (v_impact * e_rebound) * np.cos(omega * dt_post) * decay
    return disp, vel


def make_1d_drop_signals(
    t: np.ndarray,
    delay: float = 0.0,
    mag: float = 1.0,
    shape_freq: float = 25.0,
    shape_tau: float = 0.35,
    noise_std: float = 0.0,
    seed: int = 0,
) -> dict:
    """1D 낙하-바운싱 기준/시뮬레이션 신호 쌍을 생성한다.

    기준(exp)은 delay=0, mag=1, shape_freq=25, shape_tau=0.35 고정이며,
    시뮬레이션(sim)은 인자로 준 위상·크기·형태 오차를 주입한다.

    Parameters
    ----------
    t : np.ndarray
        시간 배열.
    delay : float
        sim 시간 지연 (s, 위상 노브).
    mag : float
        sim 진폭 스케일 (크기 노브).
    shape_freq : float
        sim 바운싱 각주파수 (형태 노브).
    shape_tau : float
        sim 감쇠 시정수 (형태 노브).
    noise_std : float
        sim 가산 백색노이즈 표준편차 (0이면 무노이즈).
    seed : int
        난수 시드.

    Returns
    -------
    dict
        t, disp_exp, vel_exp, disp_sim, vel_sim 키의 신호 딕셔너리.
    """
    tt = _check_time(t)
    t_shifted = np.maximum(0.0, tt - delay)
    disp_exp, vel_exp = _drop_profile(tt)
    disp_sim, vel_sim = _drop_profile(
        t_shifted, omega=shape_freq, tau=shape_tau
    )
    disp_sim = disp_sim * mag
    vel_sim = vel_sim * mag
    if noise_std > 0:
        rng = np.random.default_rng(seed)
        disp_sim = disp_sim + rng.normal(0.0, noise_std, size=tt.shape)
        vel_sim = vel_sim + rng.normal(0.0, noise_std * 10.0, size=tt.shape)
    return {
        "t": tt,
        "disp_exp": disp_exp,
        "vel_exp": vel_exp,
        "disp_sim": disp_sim,
        "vel_sim": vel_sim,
    }


def make_3d_trajectory_signals(
    t: np.ndarray,
    delay: float = 0.0,
    mag: float = 1.0,
    shape_detune: float = 0.0,
    orient_deg: float = 0.0,
    seed: int = 0,
) -> dict:
    """3D 복합 궤적 기준/시뮬레이션 신호 쌍을 생성한다.

    기준 궤적: x 등속 전진, y 횡진동, z 포물선 낙하+바운싱.
    sim은 시간 지연·전체 스케일·횡진동 디튠·XY평면 강체 회전 오차를 주입한다.

    Parameters
    ----------
    t : np.ndarray
        시간 배열.
    delay : float
        sim 시간 지연 (s, 위상 노브).
    mag : float
        sim 전체 스케일 (크기 노브).
    shape_detune : float
        sim y축 진동수 디튠 (rad/s, 형태 노브).
    orient_deg : float
        sim XY평면 회전 오차 (도, 방향 노브).
    seed : int
        난수 시드 (현재 무노이즈 구조, 재현용 예약).

    Returns
    -------
    dict
        t, disp_exp(N,3), vel_exp(N,3), disp_sim, vel_sim 딕셔너리.
    """
    tt = _check_time(t)
    _ = seed
    t_s = np.maximum(0.0, tt - delay)

    def build(t_base: np.ndarray, freq_y: float) -> np.ndarray:
        """시각 배열로부터 (N,3) 위치 궤적을 합성한다."""
        x = 2.0 * t_base
        y = 0.5 * np.sin(10.0 * t_base) if freq_y == 10.0 else 0.5 * np.sin(freq_y * t_base - 0.1)
        z_free = 10.0 - 0.5 * 9.81 * t_base**2
        z_hit = np.maximum(0.0, z_free)
        bounce = 0.6 * np.abs(np.sin(12.0 * np.maximum(0.0, t_base - 1.42))) * np.exp(
            -np.maximum(0.0, t_base - 1.42) / 0.4
        )
        z = z_hit + bounce * (z_free <= 0.0)
        return np.stack([x, y, z], axis=1)

    disp_exp = build(tt, 10.0)
    disp_sim = build(t_s, 10.0 + shape_detune) * mag
    if orient_deg != 0.0:
        th = np.deg2rad(orient_deg)
        rot = np.array(
            [[np.cos(th), -np.sin(th), 0.0],
             [np.sin(th), np.cos(th), 0.0],
             [0.0, 0.0, 1.0]]
        )
        center = np.mean(disp_sim, axis=0)
        disp_sim = (disp_sim - center) @ rot.T + center
    dt = float(np.mean(np.gradient(tt)))
    vel_exp = np.gradient(disp_exp, dt, axis=0)
    vel_sim = np.gradient(disp_sim, dt, axis=0)
    return {
        "t": tt,
        "disp_exp": disp_exp,
        "vel_exp": vel_exp,
        "disp_sim": disp_sim,
        "vel_sim": vel_sim,
    }
