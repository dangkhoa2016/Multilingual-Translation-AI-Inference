# Inline HTML/CSS template intentionally contains long presentation rules.
# ruff: noqa: E501

"""Static, bilingual public landing page for self-hosted translation APIs.

The page does not inspect runtime configuration, invoke GPU workers, expose
credentials, or fetch remote assets. Job routes require a Bearer token; public catalog reads never start GPU work.
"""

from html import escape
from string import Template

PROJECT_URL = "https://github.com/dangkhoa2016/Multilingual-Translation-AI-Inference"

COPY = {
    "en": {
        "switch_other": "Tiếng Việt",
        "nav_source": "Source code",
        "nav_guide": "Architecture",
        "health_link": "Health",
        "eyebrow": "SELF-HOSTED · MULTILINGUAL TRANSLATION API",
        "headline_top": "Four translation models.",
        "headline_bottom": "One inference gateway.",
        "intro": (
            "Build multilingual translation into your own applications with an "
            "authenticated, asynchronous API and four independently configured model backends."
        ),
        "primary": "Explore on GitHub",
        "secondary": "Deployment guide",
        "notice": (
            "A single-tenant developer API, not a public translation website. "
            "Job submission and retrieval require Bearer authentication; the model catalog is public. "
            "GPU inference is operator-controlled."
        ),
        "diagram_label": "ARCHITECTURE",
        "flow_client": "Your application",
        "flow_gateway": "CPU API gateway",
        "flow_workers": "On-demand GPU inference",
        "terminal_title": "API OVERVIEW",
        "terminal_detail": (
            "Health and the model catalog are public; job endpoints require a Bearer token. "
            "The catalog does not check live GPU readiness or activate GPUs."
        ),
        "model_heading": "Four models. One consistent API.",
        "model_desc": (
            "Select a single translation model or request multiple model runs "
            "through an asynchronous job. Each worker has its own pinned GGUF model."
        ),
        "hy_note": "Hy-MT2-30B-A3B · GGUF Q8_0 · dedicated L40S worker",
        "index_note": "Index-Translate-35B-A3B-preview · GGUF Q8_0 · dedicated L40S worker",
        "gemma_note": "Gemma 4 31B IT · GGUF Q8_0 · dedicated L40S worker",
        "qwen_note": "Qwen3.5-35B-A3B · GGUF Q8_0 · dedicated L40S worker",
        "steps_heading": "Start building",
        "steps_desc": "Deploy the gateway, connect your client and run asynchronous translation jobs.",
        "step1": "Configure your gateway",
        "step1_body": "Configure Modal, PostgreSQL, private Secrets and verified GGUF Volumes.",
        "step2": "Connect securely",
        "step2_body": "Submit and retrieve jobs using your own Bearer token. Model catalog is public.",
        "step3": "Handle async jobs",
        "step3_body": "Submit a translation, poll its job status and handle GPU cold starts.",
        "deployment_link": "Configuration guide",
        "client_link": "API security guide",
        "async_link": "Operations guide",
        "footer_note": (
            "Project source code is MIT licensed. Model weights and dependencies have "
            "their own licenses."
        ),
        "footer_links": "Reliability and limits",
    },
    "vi": {
        "switch_other": "English",
        "nav_source": "Mã nguồn",
        "nav_guide": "Kiến trúc",
        "health_link": "Trạng thái",
        "eyebrow": "API DỊCH THUẬT ĐA NGÔN NGỮ · TỰ TRIỂN KHAI",
        "headline_top": "Bốn model dịch thuật.",
        "headline_bottom": "Một cổng inference.",
        "intro": (
            "Tích hợp dịch thuật đa ngôn ngữ vào ứng dụng của bạn qua API bất đồng bộ "
            "có xác thực, với bốn model được triển khai độc lập."
        ),
        "primary": "Xem mã nguồn GitHub",
        "secondary": "Hướng dẫn triển khai",
        "notice": (
            "API dành cho hệ thống cá nhân, không phải website dịch công khai. "
            "API gửi và đọc job cần Bearer token; catalog model công khai. "
            "GPU chỉ hoạt động khi người vận hành bật."
        ),
        "diagram_label": "KIẾN TRÚC",
        "flow_client": "Ứng dụng của bạn",
        "flow_gateway": "CPU API gateway",
        "flow_workers": "GPU theo yêu cầu",
        "terminal_title": "TỔNG QUAN API",
        "terminal_detail": (
            "Health và catalog model công khai; API job yêu cầu Bearer token. "
            "Catalog không kiểm tra GPU sẵn sàng hay kích hoạt GPU."
        ),
        "model_heading": "Bốn model. Một API thống nhất.",
        "model_desc": (
            "Chọn một model để dịch hoặc so sánh nhiều model trong cùng tác vụ bất đồng bộ. "
            "Mỗi GPU worker sử dụng một bản GGUF đã khóa revision."
        ),
        "hy_note": "Hy-MT2-30B-A3B · GGUF Q8_0 · GPU worker L40S riêng",
        "index_note": "Index-Translate-35B-A3B-preview · GGUF Q8_0 · GPU worker L40S riêng",
        "gemma_note": "Gemma 4 31B IT · GGUF Q8_0 · GPU worker L40S riêng",
        "qwen_note": "Qwen3.5-35B-A3B · GGUF Q8_0 · GPU worker L40S riêng",
        "steps_heading": "Bắt đầu sử dụng",
        "steps_desc": "Triển khai gateway, kết nối ứng dụng và xử lý tác vụ dịch bất đồng bộ.",
        "step1": "Cấu hình gateway",
        "step1_body": "Cấu hình Modal, PostgreSQL, Secrets riêng tư và bốn GGUF Volumes đã xác minh.",
        "step2": "Kết nối an toàn",
        "step2_body": "Gửi và đọc job bằng Bearer token riêng. Danh sách model công khai.",
        "step3": "Xử lý job bất đồng bộ",
        "step3_body": "Gửi tác vụ dịch, lấy trạng thái job và xử lý thời gian GPU cold start.",
        "deployment_link": "Hướng dẫn cấu hình",
        "client_link": "Bảo mật API",
        "async_link": "Hướng dẫn vận hành",
        "footer_note": (
            "Mã nguồn dự án theo MIT. Trọng số model và thư viện có giấy phép riêng."
        ),
        "footer_links": "Độ tin cậy và giới hạn",
    },
}

PAGE = Template("""<!doctype html>
<html lang="$lang">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#0c1322">
  <meta name="description" content="$intro">\n  <meta name="color-scheme" content="dark">
  <title>Multilingual Translation AI Inference · API</title>
  <style>
    :root{color-scheme:dark;--bg:#0c1322;--panel:#131f33;--line:#30415b;--ink:#f1f7ff;--muted:#a3b3c9;--mint:#85e7e1;--blue:#9eb9ff}
    *{box-sizing:border-box}html{scroll-behavior:smooth}
    body{margin:0;background:radial-gradient(ellipse 65% 36% at 91% -5%,#24456d80,transparent),radial-gradient(ellipse 55% 32% at -20% 32%,#164e5280,transparent),var(--bg);color:var(--ink);font:16px/1.62 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
    a{color:inherit;text-decoration:none}a:focus-visible{outline:3px solid var(--mint);outline-offset:4px;border-radius:5px}
    .shell{max-width:1160px;margin:auto;padding:0 30px}
    .top{border-bottom:1px solid #ffffff16}.nav{display:flex;align-items:center;justify-content:space-between;gap:20px;min-height:86px}
    .identity{display:flex;align-items:center;gap:13px;font-size:15px;font-weight:750;line-height:1.3;letter-spacing:.01em}
    .mark{width:39px;height:39px;flex:none;display:grid;place-items:center;border:1px solid #60dabe80;border-radius:12px;background:linear-gradient(140deg,#164a5b,#1c3458);color:var(--mint);font-size:22px;font-weight:800}
    .navlinks{display:flex;align-items:center;gap:26px;font-size:13px;color:#c9d7e8}
    .navlinks a:hover,.footer a:hover{color:var(--mint)}
    .lang{border:1px solid #536682;border-radius:999px;padding:8px 13px;white-space:nowrap}
    .hero{display:grid;grid-template-columns:minmax(0,1.12fr) minmax(320px,.88fr);align-items:center;gap:60px;padding:106px 0 95px}
    .eyebrow{margin:0 0 22px;color:var(--mint);font-size:12px;letter-spacing:.17em;font-weight:800}
    h1{font-size:clamp(39px,4.8vw,64px);line-height:1.12;letter-spacing:-.048em;margin:0 0 26px;font-weight:800}
    h1 span{display:block;background:linear-gradient(110deg,var(--mint),#8caaff);background-clip:text;-webkit-background-clip:text;color:transparent}
    .intro{color:#bed0e5;font-size:18px;max-width:610px;margin:0 0 28px}
    .actions{display:flex;gap:12px;flex-wrap:wrap}
    .button{display:inline-flex;align-items:center;justify-content:center;gap:10px;border-radius:12px;padding:13px 18px;font-weight:750;font-size:14px;transition:transform .15s ease}
    .button:hover{transform:translateY(-2px)}.primary{background:var(--mint);color:#082132}.secondary{border:1px solid #677d98;color:#e6f0ff}
    .notice{margin:23px 0 0;max-width:590px;font-size:13px;color:var(--muted);border-left:2px solid #69a6d1;padding-left:13px}
    .visual{padding:26px;border:1px solid #3a5471;border-radius:22px;background:linear-gradient(150deg,#1b3047ee,#101a2b);box-shadow:0 25px 100px #0209186b}
    .visual-kicker{display:flex;justify-content:space-between;font-size:11px;letter-spacing:.14em;font-weight:750;color:#9db3cd;margin-bottom:21px}
    .dots{color:var(--mint);letter-spacing:2px}.path{display:grid;gap:10px}
    .node{border:1px solid #53708a;border-radius:12px;background:#1b3045;padding:13px 16px;display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:14px;font-weight:700}
    .node small{font-size:11px;color:var(--mint);font-weight:650}.arrow{text-align:center;line-height:1;color:#90b2ca}
    .worker-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.worker-grid .node{align-items:flex-start;flex-direction:column;gap:5px;font-size:12px;line-height:1.35;min-width:0;overflow-wrap:anywhere}.worker-grid .node small{font-size:10px}
    .term{border:1px solid #41516a;background:#0b1626;border-radius:13px;padding:17px;margin-top:19px}
    .term-head{color:#91aac5;letter-spacing:.09em;font-size:10px;font-weight:750;margin-bottom:10px}
    .term code{color:#b3f5df;font:12px/1.7 ui-monospace,SFMono-Regular,Consolas,monospace;overflow-wrap:anywhere}
    .term p{font-size:11px;color:#8ea5bc;margin:10px 0 0}
    .section{padding:25px 0 82px}.section h2{font-size:clamp(27px,3vw,38px);letter-spacing:-.025em;line-height:1.18;margin:0 0 12px}
    .section-lead{color:var(--muted);max-width:750px;margin:0 0 27px}
    .cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.card{border:1px solid var(--line);border-radius:17px;background:linear-gradient(145deg,#17273b,#121e30);padding:27px}
    .tag{font-size:11px;font-weight:750;letter-spacing:.11em;color:var(--mint);margin:0 0 14px}.card h3{font-size:21px;line-height:1.3;margin:0 0 14px;overflow-wrap:anywhere}
    .card code{display:inline-block;font-size:12px;background:#0b1727;border:1px solid #334861;padding:5px 9px;color:#bad5f4;border-radius:7px;overflow-wrap:anywhere;max-width:100%}
    .card .sub{font-size:14px;color:var(--muted);margin:18px 0 0}
    .steps{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:15px}.step{padding:22px 23px;border-left:2px solid #408f9e;background:#132337;border-radius:0 12px 12px 0}
    .num{font:700 12px ui-monospace,monospace;color:var(--mint)}.step h3{font-size:17px;margin:9px 0 8px}.step p{font-size:13px;color:var(--muted);margin:0 0 12px}.step a{font-size:13px;color:var(--mint);font-weight:700}
    .footer{border-top:1px solid #ffffff20;padding:28px 0 38px}.footer .shell{display:flex;justify-content:space-between;gap:22px;align-items:flex-start;color:var(--muted);font-size:12px}.footer p{margin:0;max-width:680px}
    @media(max-width:850px){.hero{grid-template-columns:1fr;gap:36px;padding:72px 0 75px}.visual{max-width:680px}.steps{grid-template-columns:1fr}.navlinks{gap:12px}}
    @media(max-width:590px){.shell{padding:0 18px}.nav{min-height:72px}.identity{font-size:12px}.mark{width:34px;height:34px}.navlinks .extra{display:none}.hero{padding:56px 0 64px}.intro{font-size:16px}.visual{padding:18px}.cards{grid-template-columns:1fr}.footer .shell{display:block}.footer p{margin-bottom:11px}}
    @media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}.button{transition:none}}
  </style>
</head>
<body>
  <header class="top">
    <nav class="shell nav" aria-label="Main navigation">
      <a class="identity" href="/" aria-label="Multilingual Translation AI Inference">
        <span class="mark" aria-hidden="true">↔</span><span>Multilingual Translation<br>AI Inference</span>
      </a>
      <div class="navlinks">
        <a class="extra" href="$project" target="_blank" rel="noopener noreferrer">$nav_source</a>
        <a class="extra" href="$architecture" target="_blank" rel="noopener noreferrer">$nav_guide</a>
        <a class="extra" href="/health">$health_link</a>
        <a class="lang" href="$other_url" hreflang="$other_lang">$switch_other</a>
      </div>
    </nav>
  </header>
  <main class="shell">
    <section class="hero" aria-labelledby="hero-heading">
      <div>
        <p class="eyebrow">$eyebrow</p>
        <h1 id="hero-heading">$headline_top <span>$headline_bottom</span></h1>
        <p class="intro">$intro</p>
        <div class="actions">
          <a class="button primary" href="$project" target="_blank" rel="noopener noreferrer">$primary <span aria-hidden="true">↗</span></a>
          <a class="button secondary" href="$deployment" target="_blank" rel="noopener noreferrer">$secondary <span aria-hidden="true">↗</span></a>
        </div>
        <p class="notice">$notice</p>
      </div>
      <div class="visual" aria-label="$diagram_label">
        <div class="visual-kicker"><span>$diagram_label</span><span class="dots" aria-hidden="true">● ● ●</span></div>
        <div class="path">
          <div class="node"><span>$flow_client</span><small>HTTPS</small></div>
          <div class="arrow" aria-hidden="true">↓</div>
          <div class="node"><span>$flow_gateway</span><small>FastAPI · Auth</small></div>
          <div class="arrow" aria-hidden="true">↓</div>
          <div class="node"><span>$flow_workers</span><small>Modal</small></div>
          <div class="worker-grid">
            <div class="node"><span>Hy-MT2-30B-A3B</span><small>L40S · Q8_0</small></div>
            <div class="node"><span>Index-Translate-35B</span><small>L40S · Q8_0</small></div>
            <div class="node"><span>Gemma 4 31B IT</span><small>L40S · Q8_0</small></div>
            <div class="node"><span>Qwen3.5-35B-A3B</span><small>L40S · Q8_0</small></div>
          </div>
        </div>
        <div class="term">
          <div class="term-head">$terminal_title</div>
          <code>GET <a href="/health">/health</a> &nbsp; · &nbsp; GET <a href="/v1/models">/v1/models</a> · public</code>
          <p>$terminal_detail</p>
        </div>
      </div>
    </section>

    <section class="section" id="models" aria-labelledby="models-heading">
      <h2 id="models-heading">$model_heading</h2>
      <p class="section-lead">$model_desc</p>
      <div class="cards">
        <article class="card">
          <p class="tag">MODEL 01 · TENCENT</p>
          <h3>tencent/Hy-MT2-30B-A3B</h3>
          <code>hy_mt2_30b</code>
          <p class="sub">$hy_note</p>
        </article>
        <article class="card">
          <p class="tag">MODEL 02 · INDEXTEAM</p>
          <h3>IndexTeam/Index-Translate-35B-A3B-preview</h3>
          <code>index_35b</code>
          <p class="sub">$index_note</p>
        </article>
        <article class="card">
          <p class="tag">MODEL 03 · GOOGLE</p>
          <h3>google/gemma-4-31B-it</h3>
          <code>gemma4_31b_it</code>
          <p class="sub">$gemma_note</p>
        </article>
        <article class="card">
          <p class="tag">MODEL 04 · QWEN</p>
          <h3>Qwen/Qwen3.5-35B-A3B</h3>
          <code>qwen35_35b</code>
          <p class="sub">$qwen_note</p>
        </article>
      </div>
    </section>

    <section class="section" id="start" aria-labelledby="steps-heading">
      <h2 id="steps-heading">$steps_heading</h2>
      <p class="section-lead">$steps_desc</p>
      <div class="steps">
        <article class="step"><span class="num">01</span><h3>$step1</h3><p>$step1_body</p><a href="$configuration" target="_blank" rel="noopener noreferrer">$deployment_link ↗</a></article>
        <article class="step"><span class="num">02</span><h3>$step2</h3><p>$step2_body</p><a href="$security" target="_blank" rel="noopener noreferrer">$client_link ↗</a></article>
        <article class="step"><span class="num">03</span><h3>$step3</h3><p>$step3_body</p><a href="$operations" target="_blank" rel="noopener noreferrer">$async_link ↗</a></article>
      </div>
    </section>
  </main>
  <footer class="footer">
    <div class="shell">
      <p>© Đăng Khoa · <a href="$project/blob/v1.0.0/LICENSE" target="_blank" rel="noopener noreferrer">MIT</a> · $footer_note</p>
      <a href="$reliability" target="_blank" rel="noopener noreferrer">$footer_links ↗</a>
    </div>
  </footer>
</body>
</html>""")


def render_landing(language: str = "en") -> str:
    """Render static public HTML; unsupported query values default to English."""
    locale = "vi" if language == "vi" else "en"
    suffix = ".vi" if locale == "vi" else ""
    values = {
        **COPY[locale],
        "lang": locale,
        "project": PROJECT_URL,
        "architecture": f"{PROJECT_URL}/blob/v1.0.0/docs/architecture{suffix}.md",
        "deployment": f"{PROJECT_URL}/blob/v1.0.0/docs/deployment{suffix}.md",
        "configuration": f"{PROJECT_URL}/blob/v1.0.0/docs/configuration{suffix}.md",
        "security": f"{PROJECT_URL}/blob/v1.0.0/docs/security{suffix}.md",
        "operations": f"{PROJECT_URL}/blob/v1.0.0/docs/operations{suffix}.md",
        "reliability": f"{PROJECT_URL}/blob/v1.0.0/docs/reliability{suffix}.md",
        "other_url": "/?lang=vi" if locale == "en" else "/?lang=en",
        "other_lang": "vi" if locale == "en" else "en",
    }
    return PAGE.substitute({key: escape(value, quote=True) for key, value in values.items()})


LANDING_RESPONSE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
}
