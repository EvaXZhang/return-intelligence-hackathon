"""Warm, projector-friendly ReMatch visual system."""

CSS = r"""
<style>
:root { --espresso:#3b2318; --cocoa:#6b3f2a; --cream:#fff8ec; --sand:#f0dfc3; --orange:#e66f2d; --sage:#477a62; }
.stApp { background: linear-gradient(145deg, #fffaf1 0%, #f7ead7 100%); color: var(--espresso); }
.block-container { max-width: 1220px; padding-top: 1.5rem; padding-bottom: 3rem; }
h1, h2, h3 { color: var(--espresso); letter-spacing: -0.025em; }
h1 { font-size: 3rem !important; }
[data-testid="stSidebar"] { background: #3b2318; }
[data-testid="stSidebar"] * { color: #fff8ec !important; }
.mode-badge { display:inline-flex; align-items:center; gap:.45rem; border-radius:999px; padding:.45rem .8rem; font-weight:800; font-size:.82rem; letter-spacing:.05em; text-transform:uppercase; }
.mode-demo { background:#dff2e8; color:#24533f; border:1px solid #9dceb7; }
.mode-aws { background:#ffeadc; color:#943f16; border:1px solid #f2ad84; }
.hero { background:linear-gradient(120deg,#3b2318,#70442c); border-radius:24px; padding:2rem 2.2rem; color:#fff8ec; box-shadow:0 16px 44px rgba(59,35,24,.18); margin-bottom:1rem; }
.hero h1,.hero h2,.hero h3,.hero p { color:#fff8ec !important; }
.hero .eyebrow { color:#f4a36f !important; font-weight:800; letter-spacing:.14em; text-transform:uppercase; font-size:.78rem; }
.card { background:rgba(255,255,255,.78); border:1px solid #ead4b4; border-radius:18px; padding:1.1rem 1.2rem; box-shadow:0 5px 18px rgba(73,45,30,.06); min-height:128px; }
.card strong { color:#6b3f2a; }
.buyer-card { border-top:5px solid #e66f2d; }
.guard-pass { color:#2c6b50; font-weight:750; }
.guard-fail { color:#a23c2b; font-weight:750; }
.stage-pill { border-left:5px solid #e66f2d; background:#fff; padding:.8rem 1rem; border-radius:4px 14px 14px 4px; margin:.35rem 0; }
.kicker { color:#b9501f; font-weight:800; text-transform:uppercase; letter-spacing:.1em; font-size:.75rem; }
.small-note { color:#715a4c; font-size:.88rem; }
.arch-local { border-top:5px solid #477a62; }
.arch-prod { border-top:5px solid #e66f2d; }
[data-testid="stMetric"] { background:#fffdf8; border:1px solid #ead4b4; padding:.85rem; border-radius:16px; }
.stButton button { border-radius:12px; font-weight:750; }
.stTabs [data-baseweb="tab"] { font-weight:750; }
</style>
"""
