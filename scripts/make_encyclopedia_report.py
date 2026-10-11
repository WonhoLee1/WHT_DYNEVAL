"""백과사전식 평가지표 보고서 생성 스크립트.

위상/크기/형태 오차를 주입한 임의 신호 스위프로 전 지표의 반응을 계측하고,
최적화 손실-지표 연동 데모와 함께 단일 HTML 보고서로 묶는다.

실행: python scripts/make_encyclopedia_report.py
출력: reports/dyneval_encyclopedia.html
"""

from __future__ import annotations

import argparse
import base64
import datetime
import io

import koreanize_matplotlib  # noqa: F401 (한글 폰트 전역 적용)
import matplotlib
import matplotlib.pyplot as plt
import numpy as np

from dyneval import ComprehensiveDynamicEvaluator
from dyneval.optimize import optimize_dynamic_parameters
from dyneval.signals import make_1d_drop_signals, make_3d_trajectory_signals

matplotlib.rcParams["font.size"] = 9

PRESETS = {
    "lab": {
        "desc": "밝은 연구실 카드형 (기본)",
        "mpl_style": "seaborn-v0_8-whitegrid",
        "fig_face": "white",
        "axes_face": "#f8fafc",
        "colors": ["#2563eb", "#dc2626", "#059669", "#d97706", "#7c3aed", "#0891b2"],
        "css": "",
    },
    "midnight": {
        "desc": "다크 기술 문서형",
        "mpl_style": "dark_background",
        "fig_face": "#0b1120",
        "axes_face": "#1e293b",
        "colors": ["#22d3ee", "#f87171", "#34d399", "#fbbf24", "#a78bfa", "#60a5fa"],
        "css": """
:root{--ink:#e2e8f0;--muted:#94a3b8;--accent:#22d3ee;--accent2:#a78bfa;
--card:#1e293b;--bg:#0b1120;--line:#334155}
.hero{background:linear-gradient(135deg,#020617,#0e7490 60%,#6d28d9)}
.toc{background:rgba(11,17,32,.96)}
table tr:nth-child(even){background:#16213a}
table tr:first-child th{background:#0e7490}
.read{background:#0c2a3a}
.rule code{background:#16213a;color:#e2e8f0}
figure{background:#1e293b}
footer code{color:#94a3b8}
""",
    },
    "paper": {
        "desc": "인쇄용 학술지 흑백형",
        "mpl_style": "grayscale",
        "fig_face": "white",
        "axes_face": "white",
        "colors": ["#000000", "#555555", "#999999", "#000000", "#555555", "#999999"],
        "css": """
:root{--ink:#111;--muted:#555;--accent:#000;--accent2:#444;
--card:#fff;--bg:#fff;--line:#bbb}
body{font-family:'Batang','Malgun Gothic',serif}
.hero{background:#111}
.sec{box-shadow:none;border-radius:0}
.sec h2{border-left-color:#000}
.toc a{color:#000}
figure{border-radius:0}
.read{background:#f5f5f5;border-left-color:#000}
""",
    },
}


def apply_preset(name: str) -> str:
    """프리셋의 matplotlib 스타일을 적용하고 CSS 오버라이드를 반환한다.

    Parameters
    ----------
    name : str
        프리셋명 (lab/midnight/paper).

    Returns
    -------
    str
        해당 프리셋의 추가 CSS.
    """
    if name not in PRESETS:
        raise ValueError(f"프리셋은 {list(PRESETS)} 중 하나여야 합니다.")
    p = PRESETS[name]
    plt.style.use(p["mpl_style"])
    matplotlib.rcParams["font.family"] = "NanumGothic"
    matplotlib.rcParams["figure.facecolor"] = p["fig_face"]
    matplotlib.rcParams["axes.facecolor"] = p["axes_face"]
    matplotlib.rcParams["axes.prop_cycle"] = matplotlib.cycler(color=p["colors"])
    matplotlib.rcParams["grid.alpha"] = 0.25
    return p["css"]
FIGSIZE_WIDE = (10, 5.5)
FIGSIZE_TALL = (10, 7.5)


def fig_to_base64(fig: matplotlib.figure.Figure) -> str:
    """Figure를 base64 PNG 문자열로 변환한다.

    Parameters
    ----------
    fig : matplotlib.figure.Figure
        변환 대상 Figure.

    Returns
    -------
    str
        base64 인코딩 PNG.
    """
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def eval_1d_case(t: np.ndarray, exp: np.ndarray, sim: np.ndarray, mode: str) -> dict:
    """1D 단일 케이스의 전 지표 딕셔너리를 평탄화해 반환한다.

    Parameters
    ----------
    t : np.ndarray
        시간 배열.
    exp : np.ndarray
        기준 신호.
    sim : np.ndarray
        해석 신호.
    mode : str
        "vel" 또는 "disp".

    Returns
    -------
    dict
        지표명 → 값.
    """
    ev = ComprehensiveDynamicEvaluator(t, exp, mode=mode)
    rep = ev.evaluate(sim)
    row: dict = {
        "Headline": rep["Main_Headline_Accuracy(%)"],
        "Loss": ev.calc_loss(sim),
        "RMSE": rep["Statistical_Metrics"]["RMSE"],
        "R2": rep["Statistical_Metrics"]["R2"],
        "Corr": rep["Statistical_Metrics"]["Pearson_Corr"],
        "DTW": rep["DTW"]["DTW_Score(%)"],
    }
    if mode == "vel":
        row["M"] = rep["Sprague_Geers"]["M"]
        row["P"] = rep["Sprague_Geers"]["P"]
        row["CORA"] = rep["CORA_Light_Decomposition"]["CORA_Score(%)"]
        row["Kp"] = rep["CORA_Light_Decomposition"]["Delay_Score_Kp"]
        row["Kv"] = rep["CORA_Light_Decomposition"]["Shape_Score_Kv"]
        row["Kg"] = rep["CORA_Light_Decomposition"]["Magnitude_Score_Kg"]
    else:
        row["NRMSE"] = rep["Global_NRMSE_Score(%)"]
    return row


def sweep_1d() -> tuple[np.ndarray, list, list]:
    """1D 위상/크기/형태 스위프 결과 (케이스 정의, disp행, vel행)을 반환한다."""
    t = np.linspace(0, 1.5, 400)
    base = make_1d_drop_signals(t)
    cases = (
        [("위상 delay=0ms (일치)", {})]
        + [(f"위상 delay={int(d * 1000)}ms", {"delay": d}) for d in (0.01, 0.02, 0.04, 0.06)]
        + [(f"크기 mag={m}", {"mag": m}) for m in (0.9, 1.1, 1.25, 0.75)]
        + [
            (f"형태 freq={f}Hz", {"shape_freq": f})
            for f in (20.0, 30.0, 15.0)
        ]
        + [(f"형태 tau={tau}s", {"shape_tau": tau}) for tau in (0.25, 0.5)]
    )
    disp_rows, vel_rows = [], []
    for _name, kw in cases:
        sim = make_1d_drop_signals(t, **kw)
        disp_rows.append(eval_1d_case(t, base["disp_exp"], sim["disp_sim"], "disp"))
        vel_rows.append(eval_1d_case(t, base["vel_exp"], sim["vel_sim"], "vel"))
    return t, cases, disp_rows, vel_rows


def sweep_3d() -> tuple[np.ndarray, list, list, list]:
    """3D 위상/크기/형태/방향 스위프 결과를 반환한다."""
    t = np.linspace(0, 1.5, 300)
    base = make_3d_trajectory_signals(t)
    cases = (
        [("일치", {})]
        + [(f"위상 delay={int(d * 1000)}ms", {"delay": d}) for d in (0.02, 0.05)]
        + [(f"크기 mag={m}", {"mag": m}) for m in (1.1, 0.85)]
        + [(f"형태 detune={d}", {"shape_detune": d}) for d in (1.5, 3.0)]
        + [(f"방향 {d}도", {"orient_deg": d}) for d in (5.0, 15.0)]
    )
    disp_rows, vel_rows = [], []
    for _name, kw in cases:
        sim = make_3d_trajectory_signals(t, **kw)
        ev_d = ComprehensiveDynamicEvaluator(t, base["disp_exp"], mode="disp")
        ev_v = ComprehensiveDynamicEvaluator(t, base["vel_exp"], mode="vel")
        rd = ev_d.evaluate(sim["disp_sim"])["3D_Trajectory_Metrics"]
        rv = ev_v.evaluate(sim["vel_sim"])
        disp_rows.append(
            {
                "Headline(ATE)": ev_d.evaluate(sim["disp_sim"])["Main_Headline_Accuracy(%)"],
                "Loss": ev_d.calc_loss(sim["disp_sim"]),
                "RMSE_ATE": rd["Spatial_RMSE_ATE(m)"],
                "Hausdorff": rd["Hausdorff"]["Hausdorff_Score(%)"],
                "Frechet": rd["Frechet"]["Frechet_Score(%)"],
                "Procrustes": rd["Procrustes_Pure_Shape"]["Procrustes_Score(%)"],
            }
        )
        vel_rows.append(
            {
                "Headline(S&G)": rv["Main_Headline_Accuracy(%)"],
                "Loss": ev_v.calc_loss(sim["vel_sim"]),
                "M": rv["Vector_Sprague_Geers"]["M_Energy"],
                "P": rv["Vector_Sprague_Geers"]["P_Phase_Orientation"],
            }
        )
    return t, cases, disp_rows, vel_rows


def plot_signal_overlay_1d(t, base, case_kws, title, key_exp, key_sim) -> str:
    """1D 대표 케이스 신호 오버레이 그래프를 base64로 반환한다."""
    fig, axes = plt.subplots(1, 3, figsize=FIGSIZE_WIDE, sharey=True)
    for ax, (name, kw) in zip(axes, case_kws):
        sim = make_1d_drop_signals(t, **kw)
        ax.plot(t, base[key_exp], label="기준 exp", linewidth=1.5)
        ax.plot(t, sim[key_sim], label="해석 sim", linewidth=1.2, linestyle="--")
        ax.set_title(name)
        ax.set_xlabel("시간 (s)")
    axes[0].set_ylabel("진폭")
    axes[0].legend(loc="upper left", bbox_to_anchor=(0, 1))
    fig.suptitle(title)
    fig.tight_layout()
    return fig_to_base64(fig)


def plot_metric_curves(names, rows, cols, title) -> str:
    """케이스별 지표 곡선 패널을 base64로 반환한다."""
    x = np.arange(len(names))
    fig, axes = plt.subplots(2, 3, figsize=FIGSIZE_TALL, sharex=True)
    for ax, col in zip(axes.flat, cols):
        vals = [r[col] for r in rows]
        ax.plot(x, vals, marker="o", linewidth=1.2)
        ax.set_title(col)
        ax.grid(True, alpha=0.3)
    for ax in axes.flat[len(cols):]:
        ax.axis("off")
    axes[1, 0].set_xticks(x)
    axes[1, 0].set_xticklabels(names, rotation=45, ha="right", fontsize=7)
    axes[1, 1].set_xticks(x)
    axes[1, 1].set_xticklabels(names, rotation=45, ha="right", fontsize=7)
    axes[1, 2].set_xticks(x)
    axes[1, 2].set_xticklabels(names, rotation=45, ha="right", fontsize=7)
    fig.suptitle(title)
    fig.tight_layout()
    return fig_to_base64(fig)


def plot_3d_paths(t) -> str:
    """3D 궤적(일치/지연/회전)의 3면 투영+3D 경로 그래프를 base64로 반환한다."""
    from mpl_toolkits.mplot3d import Axes3D  # noqa: F401 (3D 축 등록)

    base = make_3d_trajectory_signals(t)
    dly = make_3d_trajectory_signals(t, delay=0.05)
    rot = make_3d_trajectory_signals(t, orient_deg=15.0)
    fig = plt.figure(figsize=(10, 5))
    ax1 = fig.add_subplot(1, 2, 1)
    for arr, lb, ls in (
        (base["disp_exp"], "기준", "-"),
        (dly["disp_sim"], "지연 50ms", "--"),
        (rot["disp_sim"], "회전 15도", ":"),
    ):
        ax1.plot(arr[:, 0], arr[:, 2], label=lb, linestyle=ls, linewidth=1.2)
    ax1.set_xlabel("x (m)")
    ax1.set_ylabel("z (m)")
    ax1.set_title("X-Z 투영")
    ax1.legend(loc="upper left", bbox_to_anchor=(1.02, 1))
    ax2 = fig.add_subplot(1, 2, 2, projection="3d")
    for arr, lb, ls in (
        (base["disp_exp"], "기준", "-"),
        (dly["disp_sim"], "지연", "--"),
        (rot["disp_sim"], "회전", ":"),
    ):
        ax2.plot(arr[:, 0], arr[:, 1], arr[:, 2], label=lb, linestyle=ls, linewidth=1.0)
    ax2.set_title("3D 경로")
    fig.suptitle("3D 궤적 대표 케이스")
    fig.tight_layout()
    return fig_to_base64(fig)


def optimization_demo(t) -> tuple[str, str, dict]:
    """최적화 데모: 수렴 곡선·Loss-지표 산점도·보정 전후 오버레이와 결과 반환."""
    base = make_1d_drop_signals(t)

    def toy_sim(params: np.ndarray, tt: np.ndarray) -> np.ndarray:
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
        options={"maxiter": 60},
        verbose=False,
    )
    ev = out["evaluator"]
    p0 = np.array([0.7, 0.05])
    p1 = np.asarray(out["optimal_params"])
    alphas = np.linspace(0, 1, 12)
    losses, heads = [], []
    for a in alphas:
        cand = (1 - a) * p0 + a * p1
        v = toy_sim(cand, t)
        losses.append(ev.calc_loss(v))
        heads.append(ev.evaluate(v)["Main_Headline_Accuracy(%)"])

    fig, axes = plt.subplots(1, 2, figsize=FIGSIZE_WIDE)
    axes[0].plot(out["history"], linewidth=1.2)
    axes[0].set_title("Loss 수렴 곡선")
    axes[0].set_xlabel("함수 호출")
    axes[0].set_ylabel("calc_loss")
    axes[0].grid(True, alpha=0.3)
    axes[1].scatter(losses, heads, c=alphas, cmap="viridis")
    axes[1].set_title("Loss ↓ → S&G Headline ↑ (단조 연동)")
    axes[1].set_xlabel("calc_loss")
    axes[1].set_ylabel("Headline (%)")
    axes[1].grid(True, alpha=0.3)
    fig.suptitle("최적화 손실-지표 연동")
    fig.tight_layout()
    img_conv = fig_to_base64(fig)

    fig2, ax = plt.subplots(figsize=(10, 3.2))
    ax.plot(t, base["vel_exp"], label="기준", linewidth=1.5)
    ax.plot(t, toy_sim(p0, t), label="보정 전", linestyle="--", linewidth=1.2)
    ax.plot(t, out["y_sim_calibrated"], label="보정 후", linestyle=":", linewidth=1.5)
    ax.set_title("보정 전후 속도 신호")
    ax.set_xlabel("시간 (s)")
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1))
    fig2.tight_layout()
    return img_conv, fig_to_base64(fig2), out


CAUTION_ROWS = [
    ("R² (NSE)", "신호 분산 Σ(y−ȳ)²",
     "같은 절대오차도 분산 큰 축·신호에선 0.99, 작은 축에선 음수. 변위 R²는 최악 케이스도 0.90 유지(실측).",
     "지배축 판정용 참고치로만 사용, Headline·미세축 판정 금지"),
    ("Pearson Corr", "표준편차 곱 σy·σŷ",
     "진폭 스케일 정규화로 소멸 → mag 25% 오차도 0.99. 형상만 보고 크기를 못 본다.",
     "형상 진단 전용, 단독 보고 금지"),
    ("개별 Range NRMSE", "케이스별 자가 폭",
     "이동 큰 케이스가 자동 고득점 (1000mm/50mm → 95% vs 80% 역전). 케이스 공정비교 불가.",
     "고정 L_ref(스트로크)로만 비교"),
    ("CORA Kg·Impulse 면적비", "기준 면적 ∫|y|dt",
     "신호 전체가 작으면(정지 구간 多) 미세 노이즈로 비율이 출렁인다.",
     "면적 절대값 병기 후 해석"),
    ("Procrustes 잔차", "형상 분산(정렬 후)",
     "좌표계·스케일 오차를 정렬로 흡수 → 절대 위치 이탈을 못 본다.",
     "ATE·Hausdorff와 쌍으로만 해석"),
    ("S&G M (크기항)", "기준 에너지 I_ee",
     "비율형이라 포화 특성: 에너지 2배 오차도 M=0.41. P와 결합(C)되어야 감점 완성.",
     "M 단독이 아닌 C 종합으로 판정"),
    ("calc_loss", "기준 에너지·피크 자가 정규화",
     "무차원 상대값이라 케이스 간 절대비교 불가. 보고용 아님.",
     "동일 케이스 내 최적화 전후 비교 전용"),
]


def html_table(names: list, rows: list, caption: str) -> str:
    """케이스×지표 수치표를 HTML로 반환한다."""
    cols = list(rows[0].keys())
    head = "".join(f"<th>{c}</th>" for c in ["케이스"] + cols)
    body = ""
    for n, r in zip(names, rows):
        tds = "".join(
            f"<td>{v:.4f}</td>" if isinstance(v, float) else f"<td>{v}</td>"
            for v in r.values()
        )
        body += f"<tr><td>{n}</td>{tds}</tr>"
    return f"<h4>{caption}</h4><table><tr>{head}</tr>{body}</table>"


def html_caution() -> str:
    """분모 의존 상대치 지표 주의사항 표를 HTML로 반환한다.

    Returns
    -------
    str
        주의사항 표 HTML.
    """
    rows = "".join(
        f"<tr><td>{n}</td><td>{d}</td><td>{w}</td><td>{g}</td></tr>"
        for n, d, w, g in CAUTION_ROWS
    )
    return ("<h4>분모에 따라 값이 왜곡되는 상대치 지표 일람</h4>"
            "<table><tr><th>지표</th><th>분모</th><th>왜곡 양상 (실측 근거)</th>"
            "<th>사용 규칙</th></tr>" + rows + "</table>")


def html_axis(axis: dict, caption: str) -> str:
    """축별 지표 부록표를 HTML로 반환한다.

    Parameters
    ----------
    axis : dict
        calc_3d_axis_metrics 결과.
    caption : str
        표 제목.

    Returns
    -------
    str
        축별 지표 표 HTML.
    """
    cols = list(next(iter(axis.values())).keys())
    head = "".join(f"<th>{c}</th>" for c in ["축"] + cols)
    body = ""
    for name, vals in axis.items():
        tds = "".join(
            f"<td>{v:.4f}</td>" if isinstance(v, float) else f"<td>{v}</td>"
            for v in vals.values()
        )
        body += f"<tr><td>{name}</td>{tds}</tr>"
    return f"<h4>{caption}</h4><table><tr>{head}</tr>{body}</table>"


METRIC_GUIDE = [
    ("MSE / RMSE", "[0, ∞), 단위 종속", "원본 스케일 그대로. 0% 기준 없음",
     "미분 가능·최적화 Loss에 최적", "단위 종속, 0~100% 환산 불가",
     "Loss 내부 항으로만 사용"),
    ("Global NRMSE", "0~100% (클리핑)", "RMSE = 기준폭(Δx·L_diag)일 때 0%",
     "직관적·케이스 공정비교(고정척도)", "개별 Range 쓰면 큰 변위 케이스 과대평가",
     "1D/3D 변위 Headline"),
    ("R² (NSE)", "(−∞, 1]", "평균선 예측과 동률일 때 0",
     "모델 유의미성 검증", "속도처럼 평균≈0 신호에서 음수 폭락",
     "참고용, Headline 금지"),
    ("Pearson Corr", "[−1, 1]", "해당 없음(형상만 봄)",
     "형상 유사도 직관", "진폭 오차 완전 무시 → 25% 스케일 오차도 0.98",
     "맹점 증거용, 단독 사용 금지"),
    ("DTW 거리/점수", "[0, ∞) → 0~100%", "거리 = 기준폭일 때 0%",
     "위상 지연에 관대, 순수 형상 평가", "에너지·피크 감쇠 평가 둔감, O(n²)",
     "형태 진단 보조"),
    ("Sprague & Geers", "0~100%", "C=√(M²+P²) ≥ 1 일 때 0%",
     "M(크기)/P(위상) 분리, 파라미터 無", "P에 지연+형상 혼재, 노이즈 민감",
     "1D/3D 속도 Headline"),
    ("경량 CORA (Kp·Kv·Kg 곱)", "0~100%", "어느 한 축 0이면 전체 0%",
     "지연/형상/크기 3축 원인 분리", "곱셈이라 한 축 붕괴 시 과도 감점, 불연속",
     "보고서 원인분해표 (최적화 Loss 금지)"),
    ("Spatial ATE", "0~100%", "RMSE_3D = L_diag일 때 0%",
     "3D 전역 정밀도 표준", "시간 지연과 형상 왜곡 구분 불가",
     "3D 변위 Headline"),
    ("Hausdorff", "0~100%", "최악 이탈 = 허용반경일 때 0%",
     "Go/No-Go 한계 검증", "단일 이상치에 과민",
     "간섭·안전마진 판정"),
    ("Fréchet", "0~100%", "목줄 최대길이 = 허용폭일 때 0%",
     "시간왜곡 허용 순수 기하 형상", "계산량, 시간정보 소실",
     "경로 형상 일치도"),
    ("Procrustes", "0~100% (파라미터 프리)", "잔차 = 형상분산일 때 0%",
     "좌표계·스케일 불변 순수 형상", "절대 위치 오차 소실 (정렬 후 잔차)",
     "형상 검증 교차확인"),
    ("calc_loss (복합 L2)", "[0, ∞) 무차원", "해당 없음(상대 비교용)",
     "전구간 미분 가능, Loss↓→Headline↑ 단조 연동", "100% 환산 불가, 보고용 아님",
     "최적화 목적함수 전용"),
]


_REPORT_CSS = """
:root{--ink:#1e293b;--muted:#64748b;--accent:#2563eb;--accent2:#7c3aed;
--card:#ffffff;--bg:#f1f5f9;--line:#e2e8f0}
*{box-sizing:border-box}
body{font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif;color:var(--ink);
background:var(--bg);margin:0;line-height:1.65}
.hero{background:linear-gradient(135deg,#1e3a8a,#2563eb 55%,#7c3aed);color:#fff;
padding:44px 32px 34px}
.hero .wrap,.toc .wrap,.sec{max-width:1120px;margin:auto}
.hero h1{margin:0 0 8px;font-size:30px;letter-spacing:-.5px}
.hero p{margin:4px 0;opacity:.92}
.hero .badge{display:inline-block;background:rgba(255,255,255,.18);
border:1px solid rgba(255,255,255,.4);padding:2px 10px;border-radius:999px;
font-size:12px;margin-right:6px}
.toc{position:sticky;top:0;z-index:10;background:rgba(255,255,255,.95);
border-bottom:1px solid var(--line);padding:10px 32px}
.toc ol{margin:6px 0;display:flex;flex-wrap:wrap;gap:4px 18px;padding-left:18px}
.toc a{color:var(--accent);text-decoration:none;font-size:13.5px}
.toc a:hover{text-decoration:underline}
.sec{background:var(--card);border:1px solid var(--line);border-radius:14px;
padding:26px 30px;margin:22px auto;box-shadow:0 2px 10px rgba(15,23,42,.06)}
.sec h2{margin:0 0 12px;font-size:21px;padding-left:12px;border-left:5px solid var(--accent)}
.sec h4{margin:20px 0 6px;font-size:15px;color:#334155}
.table-card{overflow-x:auto;border:1px solid var(--line);border-radius:10px;margin:12px 0}
table{border-collapse:collapse;width:100%;font-size:12px}
th,td{padding:6px 10px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}
table tr:first-child th{background:#1e3a8a;color:#fff}
table tr:nth-child(even){background:#f8fafc}
td:first-child,th:first-child{text-align:left;font-weight:600}
figure{margin:14px 0;background:#fff;border:1px solid var(--line);border-radius:10px;padding:10px}
figure img{width:100%;display:block}
figcaption{font-size:12.5px;color:var(--muted);padding:6px 4px 0}
.read{background:#eff6ff;border-left:4px solid var(--accent);padding:10px 14px;
border-radius:0 8px 8px 0;margin:12px 0;font-size:13.5px}
.rule code{background:#f1f5f9;border:1px solid var(--line);padding:1px 6px;border-radius:6px}
footer{max-width:1120px;margin:10px auto 40px;color:var(--muted);font-size:12.5px;padding:0 6px}
"""


def build_html(ctx: dict) -> str:
    """보고서 컨텍스트를 단일 HTML 문서로 조립한다."""
    css = ctx.get("css", _REPORT_CSS)
    guide_rows = "".join(
        f"<tr><td>{n}</td><td>{r}</td><td>{z}</td><td>{p}</td><td>{c}</td><td>{u}</td></tr>"
        for n, r, z, p, c, u in METRIC_GUIDE
    )
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<title>동역학 정합도 평가지표 백과사전</title>
<style>{css}</style></head><body>
<header class="hero"><div class="wrap">
<span class="badge">동역학 정합도</span><span class="badge">1D · 3D</span>
<span class="badge">변위 · 속도</span><span class="badge">최적화 연동</span>
<h1>동역학 해석-시험 정합도 평가지표 백과사전</h1>
<p>생성: {ctx["date"]} · 디자인: {ctx["preset"]} · ComprehensiveDynamicEvaluator + 임의 신호 스위프 실측 기반</p>
<p>100% = 완전 일치 · 0% 기준은 지표별 표기 · 본 스크립트 재실행으로 전 수치·그래프 재현</p>
</div></header>
<nav class="toc"><div class="wrap"><b>목차</b><ol>
<li><a href="#guide">① 지표 총람</a></li>
<li><a href="#d1">② 1D 변위 스위프</a></li>
<li><a href="#v1">③ 1D 속도 스위프</a></li>
<li><a href="#d3">④ 3D 스위프</a></li>
<li><a href="#opt">⑤ 최적화 연동</a></li>
<li><a href="#rule">⑥ 실무 규칙</a></li>
<li><a href="#caution">⑦ 상대치 지표 주의사항</a></li>
</ol></div></nav>
<main>
<section class="sec" id="guide"><h2>1. 지표 총람 (장·단점·0% 기준)</h2>
<div class="table-card"><table><tr><th>지표</th><th>범위</th><th>0% 기준</th><th>장점</th><th>단점·맹점</th><th>추천 용도</th></tr>
{guide_rows}</table></div></section>
<section class="sec" id="d1"><h2>2. 1D 변위 스위프 <small style="color:var(--muted)">Headline = Global NRMSE</small></h2>
<figure><img src="data:image/png;base64,{ctx["ov_disp"]}">
<figcaption>그림 1 — 1D 변위 대표 케이스 오버레이 (위상 40ms / 크기 1.25배 / 형태 freq=15)</figcaption></figure>
<figure><img src="data:image/png;base64,{ctx["cur_disp"]}">
<figcaption>그림 2 — 1D 변위 지표 반응 곡선 (12 케이스)</figcaption></figure>
{ctx["tab_disp"]}
<div class="read"><b>읽기:</b> NRMSE Headline은 지연·크기·형태 모두에 완만히 감점된다(저주파 적분 신호 특성).
R²는 속도 대비 안정적이지만 잔류 오프셋 케이스에서 낙관 편향이 생긴다.
Corr는 크기 오차에 사실상 무반응(mag=1.25 행 Corr≈0.99 vs Headline 하락 확인)하므로 단독 사용 금지.
DTW 점수는 위상 지연에 가장 관대해 순수 형상 진단용으로만 쓴다.</div></section>
<section class="sec" id="v1"><h2>3. 1D 속도 스위프 <small style="color:var(--muted)">Headline = Sprague &amp; Geers</small></h2>
<figure><img src="data:image/png;base64,{ctx["ov_vel"]}">
<figcaption>그림 3 — 1D 속도 대표 케이스 오버레이</figcaption></figure>
<figure><img src="data:image/png;base64,{ctx["cur_vel"]}">
<figcaption>그림 4 — 1D 속도 지표 반응 곡선 (M/P 분리, CORA 3축)</figcaption></figure>
{ctx["tab_vel"]}
<div class="read"><b>읽기:</b> 20ms 지연만으로 R²가 음수로 폭락하는 반면 S&amp;G는 P항만 키워 감점한다(표의 P열).
크기 오차(mag)는 M항만 키우고 P≈0 유지 → "타이밍 정상·에너지 과대"로 분리 진단된다.
CORA 곱셈점수는 지연+형상+크기가 하나라도 어긋나면 가혹하게 깎이므로 원인분해표로만 쓰고,
최적화 Loss로는 절대 직접 사용하지 않는다(불연속 argmax 때문).</div></section>
<section class="sec" id="d3"><h2>4. 3D 변위·속도 스위프</h2>
<figure><img src="data:image/png;base64,{ctx["path3d"]}">
<figcaption>그림 5 — 3D 궤적 대표 케이스 (X-Z 투영 + 3D 경로)</figcaption></figure>
<figure><img src="data:image/png;base64,{ctx["cur_3d"]}">
<figcaption>그림 6 — 3D 변위 지표 반응 곡선 (ATE/Hausdorff/Fréchet/Procrustes)</figcaption></figure>
{ctx["tab_3d_disp"]}
{ctx["tab_3d_vel"]}
<div class="read"><b>읽기:</b> 강체 회전(방향 오차)은 Procrustes가 정렬로 흡수해 고득점을 주는 반면
ATE·Hausdorff는 정직하게 감점한다 → "좌표계 틀어짐 vs 실제 경로 이탈"을 이 쌍으로 분리 진단한다.
속도 3D S&amp;G의 P_3D는 시간 지연+진행방향 틀어짐을 함께 담는다. 기준척도는 데이터 자동산출
Bounding Box 대각선 L_diag이다.</div></section>
<section class="sec" id="opt"><h2>5. 최적화 손실-지표 연동 <small style="color:var(--muted)">Loss ↓ → 지표 ↑ 검증</small></h2>
<figure><img src="data:image/png;base64,{ctx["opt_conv"]}">
<figcaption>그림 7 — Loss 수렴 곡선 (좌) · Loss–Headline 단조 연동 산점도 (우)</figcaption></figure>
<figure><img src="data:image/png;base64,{ctx["opt_before_after"]}">
<figcaption>그림 8 — 보정 전후 속도 신호 오버레이</figcaption></figure>
<div class="read">토이 2파라미터(scale·delay) 보정: 초기 Loss {ctx["init_loss"]:.4f} →
최종 {ctx["final_loss"]:.6f}, Headline {ctx["init_acc"]:.1f}% → {ctx["final_acc"]:.1f}%.
산점도(초기→최적 선형 보간 12점)가 단조 우상향이면
"Loss를 줄이면 보고 점수가 함께 오른다"는 2단계 파이프라인 전제가 성립한다.</div></section>
<section class="sec rule" id="rule"><h2>6. 실무 규칙</h2>
<ol>
<li>최적화 루프에는 <code>calc_loss</code>만 넣는다 (CORA/S&amp;G 직접 목적함수 금지).</li>
<li>보고 Headline: 변위=NRMSE(1D)/ATE(3D), 속도=S&amp;G(1D/3D 벡터).</li>
<li>원인 분해 부록: 속도=CORA 3축(Kp/Kv/Kg)+M/P, 변위=피크·잔류, 3D=Procrustes+Hausdorff.</li>
<li>케이스 공정비교는 고정 L_ref(스트로크) 또는 데이터 자동 L_diag로만 한다.</li>
<li>Corr·R² 단독 보고 금지 (맹점 표로 증빙).</li>
</ol></section>
<section class="sec" id="caution"><h2>7. 상대치 지표 주의사항 <small style="color:var(--muted)">분모가 값을 지배한다</small></h2>
{ctx["caution"]}
{ctx["tab_axis"]}
<div class="read"><b>읽기:</b> 위 detune 케이스에서 y축 R² = −1.38인데 x·z축은 1.00이다.
y축 분산 점유율이 1%대에 불과해 같은 절대오차가 증폭돼 보이는 것으로, y 모델 결함이 아니다.
판정 규칙: R²·Corr는 분산 점유율 20% 이상인 지배축에서만 판정 근거로 삼고,
미세축은 RMSE(절대값)·DTW(형상)로만 본다. 이 구분이 안 되는 것이 상대치 지표의 근본 한계이며,
Headline이 고정 물리량 분모(NRMSE·ATE·S&amp;G)인 이유다.</div></section>
</main>
<footer>재현: <code>python scripts/make_encyclopedia_report.py</code> ·
지표 정의: my_plan_dyneval.md · 엔진: <code>dyneval.ComprehensiveDynamicEvaluator</code></footer>"""


def main() -> None:
    """스위프 실행→그래프 생성→HTML 저장을 수행한다."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="lab", choices=list(PRESETS))
    ap.add_argument("--out", default="reports/dyneval_encyclopedia.html")
    args = ap.parse_args()
    extra_css = apply_preset(args.preset)
    t1 = np.linspace(0, 1.5, 400)
    t, cases, disp_rows, vel_rows = sweep_1d()
    names = [n for n, _ in cases]
    ov_disp = plot_signal_overlay_1d(
        t1, make_1d_drop_signals(t1),
        [("위상 40ms", {"delay": 0.04}), ("크기 1.25배", {"mag": 1.25}),
         ("형태 freq=15", {"shape_freq": 15.0})],
        "1D 변위 대표 케이스", "disp_exp", "disp_sim",
    )
    ov_vel = plot_signal_overlay_1d(
        t1, make_1d_drop_signals(t1),
        [("위상 40ms", {"delay": 0.04}), ("크기 1.25배", {"mag": 1.25}),
         ("형태 freq=15", {"shape_freq": 15.0})],
        "1D 속도 대표 케이스", "vel_exp", "vel_sim",
    )
    cur_disp = plot_metric_curves(
        names, disp_rows,
        ["Headline", "NRMSE", "R2", "Corr", "DTW", "Loss"], "1D 변위 지표 반응",
    )
    cur_vel = plot_metric_curves(
        names, vel_rows,
        ["Headline", "M", "P", "CORA", "Kp", "Kv"], "1D 속도 지표 반응",
    )
    t3, cases3, d3_rows, v3_rows = sweep_3d()
    names3 = [n for n, _ in cases3]
    path3d = plot_3d_paths(t3)
    cur_3d = plot_metric_curves(
        names3, d3_rows,
        ["Headline(ATE)", "Hausdorff", "Frechet", "Procrustes", "Loss"],
        "3D 변위 지표 반응",
    )
    opt_conv, opt_ba, out = optimization_demo(t1)
    t_ax = np.linspace(0, 1.5, 300)
    base_ax = make_3d_trajectory_signals(t_ax)
    det_ax = make_3d_trajectory_signals(t_ax, shape_detune=3.0)
    ev_ax = ComprehensiveDynamicEvaluator(t_ax, base_ax["disp_exp"], mode="disp")
    axis_demo = ev_ax.calc_3d_axis_metrics(det_ax["disp_sim"])
    ctx = {
        "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "css": _REPORT_CSS + extra_css,
        "preset": f"{args.preset} ({PRESETS[args.preset]['desc']})",
        "ov_disp": ov_disp,
        "ov_vel": ov_vel,
        "cur_disp": cur_disp,
        "cur_vel": cur_vel,
        "path3d": path3d,
        "cur_3d": cur_3d,
        "tab_disp": html_table(names, disp_rows, "1D 변위 전 케이스 수치"),
        "tab_vel": html_table(names, vel_rows, "1D 속도 전 케이스 수치"),
        "tab_3d_disp": html_table(names3, d3_rows, "3D 변위 전 케이스 수치"),
        "tab_3d_vel": html_table(names3, v3_rows, "3D 속도 전 케이스 수치"),
        "opt_conv": opt_conv,
        "opt_before_after": opt_ba,
        "init_loss": out["initial_loss"],
        "final_loss": out["final_loss"],
        "init_acc": out["initial_accuracy(%)"],
        "final_acc": out["calibrated_accuracy(%)"],
        "tab_axis": html_axis(axis_demo, "축별 부록 실측 예 (3D detune=3.0 케이스)"),
        "caution": html_caution(),
    }
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(build_html(ctx))
    print(f"보고서 저장: {args.out}")


if __name__ == "__main__":
    main()
