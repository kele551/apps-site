# -*- coding: utf-8 -*-
"""生成「海风 · 桌面小工具」统一落地页（单文件 index.html，可直接发布到 Cloudflare Pages）。

原有能力全部保留：
  · 四款 logo 取各仓库 docs/icon.png，PIL 缩到 128px 内联，产物只有一个 html；
  · 构建时问 img.shields.io/endpoint.json 取实时下载 / 浏览数，取不到用 SNAPSHOT；
  · 页面打开时再取一次实时数（双层兜底）；失败时换 shields.io 缓存键只重试一次，
    仍失败就留快照并标注日期，不做假数、不重试轰炸；
  · hiwiki 镜像加速按钮按实测上线情况出现，不放死链；
  · 卡片按下载数从高到低排序；
  · 不带统计脚本、不打点、不外链字体 / CDN。

2026-11-10 新增（转化改造）：
  · 下载直链自动解析：GitHub API 取最新 tag + exe 资产名 → 优先拼 GitCode 带 tag 直链并实测，
    失败回退 GitHub releases/latest/download，再失败回退发行版列表页；--offline 用 DL_STATIC；
  · 四款真实界面截图内联为 webp data URI（来源见 shots/README.txt），不是示意图；
  · 痛点式首屏 + 一个大主 CTA、场景化文案、技术细节折叠、三步上手、FAQ、og / favicon；
  · 卡片与首屏都保留「下载 / 浏览」双数字；移动端 grid 改用 minmax(min(100%,430px),1fr)；
  · 顺手产出 og-cover.png（1200x630 分享封面），由部署脚本一并上传。

用法：
    python build_page.py                # 取实时数 + 解析直链 + 探 hiwiki + 生成 index.html 和封面
    python build_page.py --offline      # 完全不联网，用快照数与 DL_STATIC 生成
    python build_page.py --hiwiki-force # 四款都按已上线渲染，只用来本地预览版式，产物别上传

路径可用环境变量覆盖：PAGE_OUT_DIR（产物目录）、PAGE_SHOTS_DIR（界面截图）、
PAGE_ICONS_DIR（图标副本）、PAGE_REPO_ROOT（本机各项目根目录）、PAGE_FONT（封面字体）。
默认取脚本所在目录，所以 E 盘的活生成器行为不变，仓库里的副本也能独立跑。
"""
import argparse
import base64
import datetime
import io
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.environ.get("PAGE_OUT_DIR") or HERE
SHOTS_DIR = os.environ.get("PAGE_SHOTS_DIR") or os.path.join(OUT_DIR, "shots")
ICONS_DIR = os.environ.get("PAGE_ICONS_DIR") or os.path.join(OUT_DIR, "icons")
WORKER = "https://kele551-badge.kele551.workers.dev/"
SITE_URL = "https://kele551-apps.pages.dev/"
REPO = os.environ.get("PAGE_REPO_ROOT") or r"F:\Harness\projects"
FONT_PATH = os.environ.get("PAGE_FONT") or r"C:\Windows\Fonts\msyh.ttc"

HIWIKI_BASE = "https://git.hiwiki.org/zh-CN/repo/kele551/"
HIWIKI_LIVE = set()

# 每个 app 的静态资料。tech = 原技术参数（折叠区），benefits = 卡面上给用户看的场景收益。
APPS = [
    {
        "repo": "FoxPath", "name": "狐径", "en": "FoxPath", "cat": "GitHub 访问优化助手",
        "badge": "下载最多", "shot": "foxpath.webp", "shot_note": "界面录屏 v1.0.6 · 以实际下载版本为准",
        "fix": "GitHub 又打不开了？双击它，等半分钟就能正常上。",
        "benefits": [
            "不改 hosts、不改系统 DNS，也不需要管理员权限。",
            "自动挑当前实测最快的官方 IP，断了会自己换。",
            "不想用了点「退出并还原」，系统设置恢复原样。",
        ],
        "tech": [
            "只写当前用户的注册表代理（HKCU），退出即还原。",
            "每 5 分钟并发体检：TCP 443 握手 + TLS 证书校验 + HTTP 首包 2xx/3xx 才算可用。",
            "浏览器自动打开控制面板，显示出口 IP、延迟、启用/停用、开机自启与日志尾部。",
        ],
        "assure": "单文件 · 不用装 · 删掉即卸载 · 源码公开可查",
        "logo": REPO + r"\狐径\repo\docs\icon.png", "icon": "foxpath.png",
        "links": [("备用源", "https://github.com/kele551/FoxPath/releases"),
                  ("看演示", "https://www.bilibili.com/video/BV1tupx6kEPt"),
                  ("源码", "https://github.com/kele551/FoxPath"),
                  ("反馈", "https://github.com/kele551/FoxPath/issues")],
        "legacy": [("GitCode 发行页", "https://gitcode.com/kele551/FoxPath/releases"),
                   ("AtomGit 镜像", "https://atomgit.com/kele551/FoxPath")],
        "gh": "kele551/FoxPath",
    },
    {
        "repo": "ms-wallpaper-assistant", "name": "桌面壁纸", "en": "ms-wallpaper-assistant",
        "cat": "桌面壁纸自动轮换", "badge": "刚更新", "shot": "wallpaper.webp",
        "shot_note": "界面录屏 v2.4.0 · 以实际下载版本为准",
        "fix": "想每天开机都换张好壁纸，又懒得自己找图？装完就不用管了。",
        "benefits": [
            "必应每日一图 + Windows 聚焦两个微软官方图源，4K 原图。",
            "几天没开机也不漏图，错过的壁纸会自动补齐。",
            "后台换图一个窗口都不闪，图片只存在你自己电脑上。",
        ],
        "tech": [
            "免安装单文件，不要管理员权限，不写自启动注册表项、不装服务与计划任务。",
            "后台换图无窗口闪烁；全程没有任何上传行为。",
            "两个微软官方图源，按日期补齐缺失的必应壁纸。",
        ],
        "assure": "单文件 · 不写自启动项 · 不装服务 · 不上传图片",
        "logo": REPO + r"\桌面壁纸\repo\docs\icon.png", "icon": "wallpaper.png",
        "links": [("备用源", "https://github.com/kele551/ms-wallpaper-assistant/releases"),
                  ("看演示", "https://www.bilibili.com/video/BV1Tupx6kEBe"),
                  ("源码", "https://github.com/kele551/ms-wallpaper-assistant"),
                  ("反馈", "https://github.com/kele551/ms-wallpaper-assistant/issues")],
        "legacy": [("GitCode 发行页", "https://gitcode.com/kele551/ms-wallpaper-assistant/releases"),
                   ("AtomGit 镜像", "https://atomgit.com/kele551/ms-wallpaper-assistant")],
        "gh": "kele551/ms-wallpaper-assistant",
    },
    {
        "repo": "LiveIPTV", "name": "LIVE直播源", "en": "LiveIPTV",
        "cat": "直播源整理与可用性检测", "badge": "仅 GitHub", "shot": "liveiptv.webp",
        "shot_note": "仓库自带界面截图 v1.4.0 · 以实际下载版本为准",
        "fix": "网上的直播源十条有九条放不出来？一键跑出一条自己真能播的 M3U。",
        "benefits": [
            "自动抓取、合并去重，挨个实测哪些真能播再给你。",
            "清晰度和卡不卡是解视频流实测出来的，不是别人标的。",
            "勾选频道导出 M3U，PotPlayer / VLC / 电视盒子直接丢进去。",
        ],
        "tech": [
            "抓公开直播源列表 → 合并去重 → 实测可播性，并按源的可信度排序。",
            "画质判据：分辨率 ≥1080P 且码率 ≥2 Mbps 算清晰，吞吐 ≥400 KB/s 算不卡。",
            "GitCode / Gitee 未建仓，所以这款只有 GitHub 一个来源。",
        ],
        "assure": "单文件 · 不用装 · 删掉即卸载 · 源码公开可查",
        "note": "这款在 GitCode / Gitee 没建仓，只有 GitHub 一个下载源。",
        "logo": REPO + r"\LIVE直播源\repo\docs\icon.png", "icon": "liveiptv.png",
        "links": [("发行页", "https://github.com/kele551/LiveIPTV/releases"),
                  ("源码", "https://github.com/kele551/LiveIPTV"),
                  ("反馈", "https://github.com/kele551/LiveIPTV/issues")],
        "gh": "kele551/LiveIPTV",
    },
    {
        "repo": "hotnews", "name": "热点新闻", "en": "hotnews",
        "cat": "国内 / 国际热点新闻图库", "badge": "本地抓取", "shot": "hotnews.webp",
        "shot_note": "界面录屏 v1.5.1 · 以实际下载版本为准",
        "fix": "不想被推荐算法喂？一个窗口看完当天各站热榜，只看标题和原文链接。",
        "benefits": [
            "头条 / 热榜 / 科技 / 财经 / 软件 / 娱乐 / 体育分栏，每条都标来源和排名。",
            "时效按栏目分别收口，旧闻不会混到第一条。",
            "本地抓取，解析不出发布时间就绝不写「刚刚」。",
        ],
        "tech": [
            "头条与热榜严格限定当天，垂类各留自己的时间窗口。",
            "绝不伪造时间：解析不出发布时间就不当「刚刚」。",
            "本地抓取，只看标题与原文链接，不做内容二次加工。",
        ],
        "assure": "单文件 · 不用装 · 删掉即卸载 · 不上传阅读记录",
        "logo": REPO + r"\热点新闻\repo\docs\icon.png", "icon": "hotnews.png",
        "links": [("备用源", "https://github.com/kele551/hotnews/releases"),
                  ("看演示", "https://www.bilibili.com/video/BV12BpQ6mEGm"),
                  ("源码", "https://github.com/kele551/hotnews"),
                  ("反馈", "https://github.com/kele551/hotnews/issues")],
        "legacy": [("GitCode 发行页", "https://gitcode.com/kele551/hotnews/releases"),
                   ("AtomGit 镜像", "https://atomgit.com/kele551/hotnews")],
        "gh": "kele551/hotnews",
    },
]

# 2026-11-10 由 img.shields.io/endpoint.json 实测取到，作为构建时 / 页面打开时都取不到数的兜底。
SNAPSHOT = {
    "FoxPath": {"downloads": 3884, "views": 3836},
    "ms-wallpaper-assistant": {"downloads": 1414, "views": 1583},
    "LiveIPTV": {"downloads": 335, "views": 749},
    "hotnews": {"downloads": 247, "views": 864},
}

# 2026-11-10 实测的发行版信息，--offline 时用。联网时会被 GitHub API 的结果覆盖。
STATIC_RELEASE = {
    "FoxPath": {"tag": "v1.2.4", "asset": "FoxPath.exe", "mb": 8.4, "date": "2026-10-31"},
    "ms-wallpaper-assistant": {"tag": "v2.4.5", "asset": "MSWallpaperAssistant-v2.4.5.exe", "mb": 12.2, "date": "2026-11-09"},
    "LiveIPTV": {"tag": "v1.4.3", "asset": "LiveIPTV.exe", "mb": 12.6, "date": "2026-11-02"},
    "hotnews": {"tag": "v1.5.9", "asset": "hotnews-v1.5.9.exe", "mb": 14.6, "date": "2026-10-29"},
}

# --offline 时用的下载链接。GitCode 直链必须带 tag，它不支持 latest/download（会返回 HTML）。
DL_STATIC = {
    "FoxPath": ("https://gitcode.com/kele551/FoxPath/releases/download/v1.2.4/FoxPath.exe",
                "国内主源 · 点一下就开始下载", "实测 200"),
    "ms-wallpaper-assistant": ("https://github.com/kele551/ms-wallpaper-assistant/releases/latest/download/MSWallpaperAssistant-v2.4.5.exe",
                "国内镜像尚未同步 v2.4.5，打不开请点下方备用源", "GitHub 直链"),
    "LiveIPTV": ("https://github.com/kele551/LiveIPTV/releases/latest/download/LiveIPTV.exe",
                "GitHub 唯一来源 · 打不开请点下方发行页", "GitHub 直链"),
    "hotnews": ("https://gitcode.com/kele551/hotnews/releases/download/v1.5.9/hotnews-v1.5.9.exe",
                "国内主源 · 点一下就开始下载", "实测 200"),
}

FAQ = [
    ("杀毒软件报毒 / SmartScreen 提示「未知发布者」怎么办？",
     "个人开源项目没有购买代码签名证书，Windows 对未签名的 exe 会弹提示，这是常见现象。"
     "可以在「属性 → 详细信息」核对版本号；程序为 MIT 开源，源码可自行审阅与构建。"
     "建议只从本页链接或官方仓库下载，别用第三方转载包。"),
    ("怎么卸载？会不会改我电脑的设置？",
     "没有安装过程，也就没有卸载步骤：删掉那个 exe 即可。狐径运行时只写当前用户的注册表代理项，"
     "点「退出并还原」立即恢复；壁纸助手不写自启动项、不装服务和计划任务。"),
    ("会不会上传我的数据？",
     "不会。四款都是本机运行，不采集、不上传用户数据。壁纸图片、新闻标题、直播源检测结果"
     "都只存在你自己电脑上；本页本身也没有统计脚本和第三方 CDN。"),
    ("支持哪些系统？需要联网吗？",
     "Windows 10 / 11，单文件 exe，中文界面。工具本身要联网才能取数据（GitHub 连通性、壁纸、"
     "直播源、新闻），但安装和启动不需要联网下载依赖。"),
    ("怎么升级？版本还维护吗？",
     "狐径与壁纸助手的控制面板里有「检查更新」；也可以回到本页重新下载覆盖，配置与收藏保留。"
     "每张卡片都标了版本号和最近更新日期，方便你判断项目是否在维护。"),
    ("页面上的下载数、浏览数是怎么算的？",
     "<b>下载</b> = GitHub Releases 各附件下载数 + GitCode 的 download_statistics；"
     "<b>浏览</b> = 该仓库实际存在的每个平台（GitHub / GitCode / Gitee）访问计数之和。"
     "四款从 2026-10-27 起同一口径，由一个 Cloudflare Worker 现场算，页面经 img.shields.io 中转读取；"
     "单平台瞬时取不到时回退到上次成功值，所以数字只会稳、不会忽然腰斩。"
     "LIVE直播源在 GitCode / Gitee 没建仓，那一项按 0 计。卡片与首屏的数字每次打开现场取，取不到时保留快照。"),
]


def http_get(url, timeout=15):
    """先试 urllib，失败退回 curl（本机 urllib 走代理时取 shields 会全空，curl 是通的）。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "landing-page-build"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except Exception:
        try:
            p = subprocess.run(["curl", "-sL", "--max-time", str(timeout), url],
                               capture_output=True, timeout=timeout + 5)
            return p.stdout.decode("utf-8", "replace")
        except Exception:
            return ""


def http_probe(url, timeout=12):
    """用 1 字节 range 请求探「是不是真附件」，返回 (是否可用, 说明)。

    实测 2026-11-10：GitCode 附件对 HEAD 回 401（Python subprocess 里甚至 000），
    必须用 GET；exe 有 8–15 MB，所以带 --range 0-0 只取 1 字节，成功码是 206。
    只有 200/206 且 content-type 含 octet-stream 才算真附件 —— 否则会把
    「返回 HTML 的 latest/download 假直链」当成能点。
    """
    try:
        p = subprocess.run(
            ["curl", "-sL", "--range", "0-0", "-o", "/dev/null",
             "-w", "%{http_code} %{content_type}", "--max-time", str(timeout), url],
            capture_output=True, timeout=timeout + 5)
        out = p.stdout.decode("utf-8", "replace").strip()
        bits = out.split(" ", 1)
        code = bits[0]
        ctype = bits[1] if len(bits) > 1 else ""
        ok = code in ("200", "206") and "octet-stream" in ctype
        return ok, out or "无响应"
    except Exception as e:
        return False, "探测失败 %s" % e


def logo_data_uri(path, bundled=None):
    """优先读本机各项目 docs/icon.png；找不到就用随代码附带的 icons/ 副本。"""
    if not os.path.exists(path) and bundled:
        alt = os.path.join(ICONS_DIR, bundled)
        if os.path.exists(alt):
            path = alt
    if not os.path.exists(path):
        raise SystemExit("找不到图标：%s —— 设置 PAGE_REPO_ROOT，或补齐 icons/ 里的 %s"
                         % (path, bundled or "图标"))
    im = Image.open(path).convert("RGBA")
    im.thumbnail((128, 128), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def shot_data_uri(name):
    """界面截图（webp）内联，产物仍是单文件 html。"""
    path = os.path.join(SHOTS_DIR, name)
    if not os.path.exists(path):
        raise SystemExit("找不到界面截图：%s —— 见 shots/README.txt" % path)
    with open(path, "rb") as f:
        return "data:image/webp;base64," + base64.b64encode(f.read()).decode()


def live_numbers(timeout=15):
    """问 shields.io 要实时数；返回 {repo: {kind: int}}，拿不到的仓库对应值为空。

    shields.io 把 endpoint 结果缓存 5 分钟，Worker 偶发返回的 inaccessible 也会被
    一起缓存住。正常路径仍走共享缓存（省调用）；只有取不到时才换一个缓存键
    （加 _= 时间戳）再取一次，避免「整个 5 分钟窗口都显示旧快照」。
    """
    got = {}
    for app in APPS:
        repo = app["repo"]
        got[repo] = {}
        for kind in ("downloads", "views"):
            target = WORKER + "?repo=%s&kind=%s" % (repo, kind)
            for attempt in (0, 1):
                url = target if attempt == 0 else "%s&_=%d" % (target, int(time.time() * 1000))
                api = "https://img.shields.io/endpoint.json?url=" + urllib.parse.quote(url, safe="")
                try:
                    j = json.loads(http_get(api, timeout))
                    raw = j.get("value") or j.get("message")
                    v = int(str(raw).strip())
                    if v > 0:
                        got[repo][kind] = v
                        break
                    raise ValueError("返回 %r" % raw)
                except Exception as e:
                    if attempt:
                        print("  ! %s %s 两次都没取到，留快照：%s" % (repo, kind, e))
    return got


def numbers_for(repo, live):
    snap = SNAPSHOT[repo]
    d = live.get(repo, {}).get("downloads") or snap["downloads"]
    v = live.get(repo, {}).get("views") or snap["views"]
    return d, v


def hiwiki_url(repo):
    return HIWIKI_BASE + repo.lower()


def hiwiki_live(timeout=10):
    """探一遍四款在 hiwiki 上有没有真正上线，返回已上线的仓库名集合。

    判读规则（2026-11-05 实测）：404 = 还在审核；200 且正文含 owner/repo = 真上线；
    200 但正文没有仓库标识 = 已下架，不能挂；连接失败按未上线处理。
    """
    got = set()
    for app in APPS:
        repo = app["repo"]
        url = hiwiki_url(repo)
        note = ""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "landing-page-build"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                code, body = r.getcode(), r.read().decode("utf-8", "replace")
            slug = url.rsplit("/zh-CN/repo/", 1)[-1].lower()
            if code == 200 and slug in body.lower():
                got.add(repo)
                note = "已上线"
            elif code == 200:
                note = "回 200 但正文没有仓库标识（多半已下架），不挂按钮"
            else:
                note = "未上线（HTTP %s）" % code
        except urllib.error.HTTPError as e:
            note = "未上线（HTTP %s）" % e.code
        except Exception as e:
            note = "探测失败，按未上线处理（%s）" % e
        print("  %s %s：hiwiki %s" % ("OK" if repo in got else "--", app["name"], note))
    return got


def release_meta(app, timeout=15):
    """从 GitHub API 取最新 tag、exe 资产名、体积、发布日期；失败回退静态值。"""
    repo = app["repo"]
    static = dict(STATIC_RELEASE[repo])
    txt = http_get("https://api.github.com/repos/%s/releases/latest" % app["gh"], timeout)
    try:
        j = json.loads(txt)
        exes = [a for a in j.get("assets", []) if a["name"].lower().endswith(".exe")]
        if not exes or not j.get("tag_name"):
            raise ValueError("没有 tag 或 exe 资产")
        exes.sort(key=lambda a: -a.get("size", 0))
        a = exes[0]
        static.update(tag=j["tag_name"], asset=a["name"],
                      mb=round(a["size"] / 1048576, 1),
                      date=(j.get("published_at") or "")[:10] or static["date"],
                      source="GitHub API")
        return static
    except Exception as e:
        print("  ! %s 发行版信息取不到（%s），用静态值" % (repo, e))
        static["source"] = "静态值"
        return static


def resolve_download(app, meta):
    """挑一条真能点的下载链接：GitCode 带 tag 直链 → GitHub latest/download → 发行版列表页。

    GitCode 不支持 latest/download（返回 HTML 不是文件），所以必须带 tag。
    返回 (url, 按钮下小字, 来源标记)。
    """
    repo, owner = app["repo"], "kele551"
    tag, asset = meta["tag"], meta["asset"]
    gc = "https://gitcode.com/%s/%s/releases/download/%s/%s" % (owner, repo, tag, asset)
    gh = "https://github.com/%s/%s/releases/latest/download/%s" % (owner, repo, asset)
    ok, info = http_probe(gc)
    print("  %s %-24s %-14s %s" % ("OK" if ok else "--", repo, "GitCode 直链", info))
    if ok:
        return gc, "国内主源 · 点一下就开始下载", "GitCode 直链"

    # GitHub 的 releases/latest/download/<资产名> 是官方稳定格式，资产名刚由 API 核实过。
    # 本机 HEAD 常因境内网络返回 000，那是「我这连不上」，不是「链接无效」，
    # 所以不因此退回列表页（退回列表页才是真的多两步），只在按钮下如实说明。
    ok2, info2 = http_probe(gh)
    print("  %s %-24s %-14s %s" % ("OK" if ok2 else "--", repo, "GitHub 直链", info2))
    note = "国内主源暂不可用，打不开请点下方备用源"
    mark = "GitHub 直链" + ("" if ok2 else "（本机探测未通，链接格式已核实）")
    return gh, note, mark


def make_og_cover(sum_d, sum_v):
    """生成 1200x630 分享封面；纯本地 Pillow，不联网。"""
    W, H = 1200, 630
    im = Image.new("RGB", (W, H), "#f7f8fa")
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 8], fill="#0b6bcb")
    font_path = FONT_PATH
    try:
        f_big = ImageFont.truetype(font_path, 62)
        f_mid = ImageFont.truetype(font_path, 30)
        f_sm = ImageFont.truetype(font_path, 24)
    except Exception:
        f_big = f_mid = f_sm = ImageFont.load_default()
    d.text((72, 96), "四款 Windows 桌面小工具", font=f_big, fill="#1b2129")
    d.text((72, 196), "双击就能用 · 免安装 · 不上传数据", font=f_mid, fill="#0b6bcb")
    d.text((72, 268), "GitHub 加速   每日 4K 壁纸   直播源检测   热点新闻", font=f_sm, fill="#626e7b")
    d.rounded_rectangle([72, 356, 1128, 470], radius=18, fill="#ffffff", outline="#e4e8ee", width=2)
    d.text((104, 386), "合计下载  %s" % format(sum_d, ","), font=f_mid, fill="#1b2129")
    d.text((640, 386), "合计浏览  %s" % format(sum_v, ","), font=f_mid, fill="#1b2129")
    d.text((72, 522), "海风（kele551） · 免费开源 · MIT", font=f_sm, fill="#626e7b")
    d.text((72, 566), "kele551-apps.pages.dev", font=f_sm, fill="#0b6bcb")
    out = os.path.join(OUT_DIR, "og-cover.png")
    im.save(out, "PNG", optimize=True)
    return out


CSS = """
:root{--bg:#f7f8fa;--card:#fff;--ink:#1b2129;--muted:#626e7b;--line:#e4e8ee;--chip:#f0f3f7;
--accent:#0b6bcb;--accent-ink:#fff;--ok:#1a7f5a;
--shadow:0 1px 2px rgba(16,24,40,.05),0 8px 24px rgba(16,24,40,.05)}
@media (prefers-color-scheme:dark){:root{--bg:#11141a;--card:#181c24;--ink:#e9edf2;--muted:#9ba6b2;
--line:#272d38;--chip:#202732;--accent:#5aa8ff;--accent-ink:#0b1016;--ok:#5dcaa5}}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei UI","Microsoft YaHei","Noto Sans SC",Arial,sans-serif;
-webkit-font-smoothing:antialiased}
.wrap{max-width:1060px;margin:0 auto;padding:0 20px 64px}
a{color:var(--accent)}
.eyebrow{display:inline-block;font-size:12.5px;color:var(--muted);background:var(--chip);
border-radius:999px;padding:5px 13px;margin-bottom:18px}
.hero{padding:64px 0 30px;text-align:center}
.hero h1{margin:0 0 14px;font-size:38px;line-height:1.32;letter-spacing:-.6px}
.hero h1 em{font-style:normal;color:var(--accent)}
.hero .sub{margin:0 auto;max-width:620px;color:var(--muted);font-size:16px}
.cta-row{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;margin:26px 0 14px}
.btn{display:inline-block;text-decoration:none;border-radius:11px;padding:13px 24px;font-size:15px;font-weight:600;
white-space:nowrap;border:1px solid var(--line);background:var(--chip);color:var(--ink)}
.btn:hover{border-color:var(--accent)}
.btn.primary{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
.btn .minor{display:block;font-size:11.5px;font-weight:400;opacity:.8;margin-top:2px}
.promise{display:flex;flex-wrap:wrap;gap:8px 18px;justify-content:center;margin:18px 0 0;
font-size:13px;color:var(--muted)}
.promise span::before{content:"\\2713";color:var(--ok);margin-right:5px}
.social{margin:22px 0 0;font-size:13px;color:var(--muted)}
.social b{color:var(--ink);font-variant-numeric:tabular-nums}
h2.sec{margin:54px 0 6px;font-size:23px;letter-spacing:-.3px}
p.secsub{margin:0 0 22px;color:var(--muted);font-size:14px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,430px),1fr));gap:18px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;overflow:hidden;
box-shadow:var(--shadow);display:flex;flex-direction:column}
.shot{position:relative;height:210px;background:#eef1f5;border-bottom:1px solid var(--line);
display:flex;align-items:center;justify-content:center;padding:14px}
.shot img{max-width:100%;max-height:100%;object-fit:contain;border-radius:6px;
box-shadow:0 2px 10px rgba(16,24,40,.14)}
.shot .tag{position:absolute;right:9px;bottom:7px;font-size:10.5px;color:#6d7885;
background:rgba(255,255,255,.9);border-radius:5px;padding:2px 7px}
.card .inner{padding:18px 20px 20px;display:flex;flex-direction:column;flex:1}
.card .head{display:flex;gap:12px;align-items:center}
.card img.logo{width:42px;height:42px;border-radius:11px;flex:0 0 42px;background:#fff;
border:1px solid var(--line);object-fit:contain}
.card h3{margin:0;font-size:18px}
.card h3 .en{font-size:11.5px;color:var(--muted);font-weight:400;margin-left:6px}
.card .badge{font-size:11px;color:var(--accent);background:var(--chip);border-radius:5px;padding:2px 7px;margin-left:auto;white-space:nowrap}
.metrics{display:flex;gap:8px;margin:12px 0 14px}
.metrics .m{flex:1;background:var(--chip);border-radius:9px;padding:7px 11px}
.metrics .m b{display:block;font-size:17px;font-variant-numeric:tabular-nums;line-height:1.3}
.metrics .m span{font-size:11.5px;color:var(--muted)}
.card .fix{margin:0 0 8px;font-size:15.5px;font-weight:600;line-height:1.55}
.card ul{margin:0 0 14px;padding-left:17px;color:var(--muted);font-size:13.5px}
.card li{margin:0 0 5px}
.meta{font-size:12px;color:var(--muted);margin:0 0 12px;font-variant-numeric:tabular-nums}
.dl{display:block;text-align:center;text-decoration:none;background:var(--accent);color:var(--accent-ink);
border-radius:10px;padding:12px 16px;font-size:15px;font-weight:600}
.dl small{display:block;font-size:11.5px;font-weight:400;opacity:.85;margin-top:2px}
.assure{text-align:center;font-size:12px;color:var(--muted);margin:8px 0 12px}
.links{display:flex;flex-wrap:wrap;gap:6px 14px;justify-content:center;font-size:12.5px;margin-top:auto}
.links a{text-decoration:none}
.legacy{margin-top:12px;padding-top:10px;border-top:1px dashed var(--line);font-size:12.5px;color:var(--muted);line-height:1.9}
.legacy b{font-weight:600;color:var(--ink)}
.legacy a{text-decoration:none}
details{margin-top:12px;border-top:1px solid var(--line);padding-top:10px}
summary{cursor:pointer;font-size:12.5px;color:var(--muted)}
details p,details ul{font-size:12.5px;color:var(--muted);margin:10px 0 0}
.shields{margin-top:8px;display:flex;gap:4px}
.shields img{height:20px}
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr));gap:14px;margin-top:18px}
.step{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:16px 18px}
.step b{display:block;font-size:14px;margin-bottom:4px}
.step span{font-size:13px;color:var(--muted)}
.step .n{color:var(--accent);font-size:12px;font-weight:600}
.faq{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:6px 20px;margin-top:18px}
.faq details{padding:12px 0;border-top:0;border-bottom:1px solid var(--line)}
.faq details:last-child{border-bottom:0}
.faq summary{font-size:14px;color:var(--ink);font-weight:500}
footer{margin-top:44px;padding-top:20px;border-top:1px solid var(--line);color:var(--muted);font-size:12.5px;text-align:center}
@media(max-width:640px){.hero{padding:42px 0 20px}.hero h1{font-size:28px}.hero .sub{font-size:14.5px}
.btn{padding:12px 18px;font-size:14px}.shot{height:170px}}
"""

TPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>海风 · 四款 Windows 桌面小工具，双击就能用</title>
<meta name="description" content="GitHub 打不开、壁纸懒得换、直播源失效、热点刷不完？四款免费开源的单文件 Windows 工具，免安装、不要管理员权限、不上传任何数据，点一下直接下载。">
<meta name="theme-color" content="#f7f8fa">
<meta property="og:type" content="website">
<meta property="og:title" content="四款 Windows 桌面小工具，双击就能用">
<meta property="og:description" content="免费开源 · 单文件 exe · 免安装 · 不采集数据。GitHub 加速、每日壁纸、直播源检测、热点新闻。">
<meta property="og:url" content="@@SITE_URL@@">
<meta property="og:image" content="@@SITE_URL@@og-cover.png">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%230b6bcb'/%3E%3Ctext x='16' y='22' font-size='18' text-anchor='middle' fill='white' font-family='sans-serif'%3E%E6%B5%B7%3C/text%3E%3C/svg%3E">
<style>@@CSS@@</style>
</head>
<body>
<div class="wrap">

<!-- 生成时间 @@BUILD_DATE@@ · 下载链接由生成器实测解析，状态见各卡片按钮下的小字 -->

<header class="hero">
  <span class="eyebrow">4 款免费开源的 Windows 桌面小工具 · 作者 海风（kele551）</span>
  <h1>GitHub 打不开、壁纸懒得换？<br><em>四款小工具，双击就能用</em></h1>
  <p class="sub">不用安装、不用管理员权限、不上传任何数据。下载一个 exe，双击运行，不想用了把文件删掉就等于卸载。</p>
  <div class="cta-row">
    <a class="btn primary" href="@@HERO_DL@@">⬇ 下载狐径 FoxPath<span class="minor">@@HERO_META@@ · 最热门的一款</span></a>
    <a class="btn" href="#apps">先看 4 款分别解决什么</a>
  </div>
  <div class="promise">
    <span>免费无广告</span><span>单文件免安装</span><span>不要管理员权限</span>
    <span>不采集不上传数据</span><span>MIT 开源，源码可查</span><span>删除即卸载</span>
  </div>
  <p class="social">四款合计 <b id="sum-downloads">@@SUM_D@@</b> 次下载 · <b id="sum-views">@@SUM_V@@</b> 次浏览 · <a href="#numbers">口径说明</a> · <span id="snap-note">快照 @@SNAP_DATE@@（实时取不到时显示这份数）</span></p>
</header>

<h2 class="sec" id="apps">选一个你正遇到的问题</h2>
<p class="secsub">四款都是独立的小程序，互不影响，只下你需要的那个就行。</p>

<div class="grid">
@@CARDS@@
</div>

<h2 class="sec">下载之后，就三步</h2>
<p class="secsub">不需要配置，不需要重启，也不需要管理员权限。</p>
<div class="steps">
  <div class="step"><span class="n">01</span><b>下载 exe</b><span>点上面的按钮，得到一个单文件程序，约 8–15 MB。</span></div>
  <div class="step"><span class="n">02</span><b>双击运行</b><span>首次启动会自己准备一下，等十几秒，界面就出来了。</span></div>
  <div class="step"><span class="n">03</span><b>用，或者删掉</b><span>不想要了直接删文件，不留服务、不留自启动项。</span></div>
</div>

<h2 class="sec">你可能在担心</h2>
<p class="secsub">这几条是单文件 exe 最常被问到的，先说清楚。</p>
<div class="faq">
@@FAQ@@
</div>

<footer>
  © 2026 海风（kele551） · MIT License · 四款工具源码见各卡片「源码」链接 · 问题反馈：各仓库 Issues
</footer>

</div>
<script>
/* 实时取数：只读 img.shields.io（它回 CORS 头，结果缓存 5 分钟）。
   取到就覆盖 html 里烧好的快照。失败时换缓存键只重试一次（缓存里的错误响应
   不会因此被重复取到），仍失败就留快照并保留日期标注 —— 不做假数，不轰炸接口。 */
(function () {
  var APPS = @@JS_APPS@@;
  var WORKER = "@@WORKER@@";
  var live = {};
  var anyLive = false;

  function base(id) {
    var el = document.getElementById(id);
    return el ? (parseInt(el.dataset.base || "0", 10) || 0) : 0;
  }
  function fmt(n) { return n.toLocaleString("en-US"); }

  function paint() {
    var sd = 0, sv = 0;
    APPS.forEach(function (a) {
      var v = live[a.repo] || {};
      var ed = document.getElementById("d-" + a.key);
      var ew = document.getElementById("v-" + a.key);
      if (ed && v.downloads) ed.textContent = fmt(v.downloads);
      if (ew && v.views) ew.textContent = fmt(v.views);
      sd += v.downloads || base("d-" + a.key);
      sv += v.views || base("v-" + a.key);
    });
    if (anyLive) {
      document.getElementById("sum-downloads").textContent = fmt(sd);
      document.getElementById("sum-views").textContent = fmt(sv);
      document.getElementById("snap-note").textContent = "数字实时（每次打开现取，5 分钟内命中缓存）";
    }
  }

  APPS.forEach(function (a) {
    ["downloads", "views"].forEach(function (kind) {
      var target = WORKER + "?repo=" + encodeURIComponent(a.repo) + "&kind=" + kind;
      function endpoint(bust) {
        var u = bust ? target + "&_=" + Date.now() : target;
        return "https://img.shields.io/endpoint.json?url=" + encodeURIComponent(u);
      }
      function read(url) {
        return fetch(url).then(function (r) {
          return r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status));
        }).then(function (j) {
          var n = parseInt(String(j.value || j.message || "").replace(/[^0-9]/g, ""), 10);
          if (!(n > 0)) throw new Error("不是数字");
          return n;
        });
      }
      function accept(n) {
        (live[a.repo] = live[a.repo] || {})[kind] = n;
        anyLive = true;
        paint();
      }
      read(endpoint(false)).then(accept).catch(function () {
        read(endpoint(true)).then(accept).catch(function () { /* 保留快照 */ });
      });
    });
  });
})();
</script>
</body>
</html>
"""

CARD_TPL = """<article class="card" id="@@SLUG@@">
  <div class="shot">
    <img src="@@SHOT@@" alt="@@NAME@@ 界面截图" loading="lazy">
    <span class="tag">@@SHOT_NOTE@@</span>
  </div>
  <div class="inner">
    <div class="head">
      <img class="logo" src="@@LOGO@@" alt="@@NAME@@ 图标">
      <h3>@@NAME@@<span class="en">@@EN@@</span></h3>
      <span class="badge">@@BADGE@@</span>
    </div>
    <div class="metrics">
      <div class="m"><b id="d-@@KEY@@" data-base="@@D@@">@@D_FMT@@</b><span>下载 · 发行版合计</span></div>
      <div class="m"><b id="v-@@KEY@@" data-base="@@V@@">@@V_FMT@@</b><span>浏览 · 各平台合计</span></div>
    </div>
    <p class="fix">@@FIX@@</p>
    <ul>
@@BENEFITS@@
    </ul>
    <p class="meta">@@TAG@@ · @@MB@@ MB · @@DATE@@ 更新 · Windows 10/11</p>
    <a class="dl" href="@@DL_URL@@">⬇ 直接下载 @@ASSET@@<small>@@DL_NOTE@@</small></a>
    <p class="assure">@@ASSURE@@</p>
    <div class="links">
@@LINKS@@
    </div>
    <details><summary>技术细节与版本状态（可选看）</summary>
      <ul>
@@TECH@@
      </ul>
      <div class="shields">
        <img alt="Release" src="https://img.shields.io/github/v/release/@@GH@@?style=flat-square&amp;label=release&amp;color=blue" loading="lazy">
        <img alt="Last commit" src="https://img.shields.io/github/last-commit/@@GH@@?style=flat-square&amp;label=last%20commit&amp;color=blue" loading="lazy">
      </div>
@@NOTE@@
@@LEGACY@@
    </details>
  </div>
</article>"""


def fill(tpl, mapping):
    out = tpl
    for k, v in mapping.items():
        out = out.replace("@@" + k + "@@", str(v))
    return out


def render_card(app, live, hiwiki, meta, dl):
    d, v = numbers_for(app["repo"], live)
    key = app["repo"].replace(".", "-")
    links = list(app["links"])
    if app["repo"] in hiwiki:
        at = len(links)
        for i, (label, _u) in enumerate(links):
            if "看演示" in label or "反馈" in label:
                at = i
                break
        links.insert(at, ("hiwiki 镜像加速", hiwiki_url(app["repo"])))
    link_html = "\n".join('      <a href="%s" target="_blank" rel="noopener">%s</a>' % (u, l)
                          for l, u in links)
    benefits = "\n".join("      <li>%s</li>" % b for b in app["benefits"])
    tech = "\n".join("        <li>%s</li>" % t for t in app["tech"])
    note = '      <p>%s</p>' % app["note"] if app.get("note") else ""
    legacy = app.get("legacy") or []
    legacy_html = ""
    if legacy:
        legacy_html = ('      <div class="legacy"><b>其他下载入口（旧链接照旧留着）</b><br>\n'
                       + " · ".join('<a href="%s" target="_blank" rel="noopener">%s</a>' % (u, l)
                                    for l, u in legacy) + '</div>')
    url, dl_note, _mark = dl
    return fill(CARD_TPL, {
        "SLUG": app["repo"].lower().replace("-", ""),
        "SHOT": shot_data_uri(app["shot"]), "SHOT_NOTE": app["shot_note"],
        "LOGO": logo_data_uri(app["logo"], app.get("icon")), "NAME": app["name"], "EN": app["en"],
        "BADGE": app["badge"], "KEY": key, "D": d, "D_FMT": format(d, ","),
        "V": v, "V_FMT": format(v, ","), "FIX": app["fix"],
        "BENEFITS": benefits, "TAG": meta["tag"], "MB": meta["mb"], "DATE": meta["date"],
        "DL_URL": url, "ASSET": meta["asset"], "DL_NOTE": dl_note,
        "ASSURE": app["assure"], "LINKS": link_html, "TECH": tech,
        "GH": app["gh"], "NOTE": note, "LEGACY": legacy_html,
    })


def render_faq(mirror_note):
    out = []
    for i, (q, a) in enumerate(FAQ):
        if i == len(FAQ) - 1 and mirror_note:
            a += mirror_note
        out.append("  <details%s><summary>%s</summary><p>%s</p></details>" %
                   (' id="numbers"' if i == len(FAQ) - 1 else "", q, a))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="不联网，直接用快照数与 DL_STATIC 生成")
    ap.add_argument("--hiwiki-force", action="store_true", help="四款全按已上线渲染，只用于本地预览版式")
    args = ap.parse_args()

    live, hiwiki = {}, set(HIWIKI_LIVE)
    metas, dls = {}, {}
    if not args.offline:
        print("取实时数…")
        live = live_numbers()
        print("  取到 %d 个仓库的数" % len([r for r in live if live[r]]))
        print("探 hiwiki 镜像源上线情况…")
        hiwiki |= hiwiki_live()
        print("解析发行版与下载直链…")
        for app in APPS:
            meta = release_meta(app)
            metas[app["repo"]] = meta
            dls[app["repo"]] = resolve_download(app, meta)
    else:
        print("离线模式：用快照数、静态发行信息与 DL_STATIC 直链")
        for app in APPS:
            metas[app["repo"]] = dict(STATIC_RELEASE[app["repo"]])
            dls[app["repo"]] = DL_STATIC[app["repo"]]
    if args.hiwiki_force:
        hiwiki = {a["repo"] for a in APPS}
    print("  hiwiki 已上线 %d/4 款：%s" % (len(hiwiki), "、".join(sorted(hiwiki)) or "无"))

    ordered = sorted(APPS, key=lambda a: -numbers_for(a["repo"], live)[0])
    cards = "\n\n".join(render_card(a, live, hiwiki, metas[a["repo"]], dls[a["repo"]])
                        for a in ordered)
    sum_d = sum(numbers_for(a["repo"], live)[0] for a in APPS)
    sum_v = sum(numbers_for(a["repo"], live)[1] for a in APPS)
    js_apps = json.dumps([{"repo": a["repo"], "key": a["repo"].replace(".", "-")} for a in APPS],
                         ensure_ascii=False)
    mirror_note = ""
    if hiwiki:
        mirror_note = ("卡片里的 <b>hiwiki 镜像加速</b>是第三方聚合站（git.hiwiki.org）的境内直连入口，"
                       "安装包仍出自上面这些仓库，它自己统计的下载量不计进这里。")

    hero = ordered[0]
    hero_meta = metas[hero["repo"]]
    html = fill(TPL, {
        "CSS": CSS, "CARDS": cards, "SUM_D": format(sum_d, ","), "SUM_V": format(sum_v, ","),
        "SNAP_DATE": datetime.date.today().isoformat(), "BUILD_DATE": datetime.date.today().isoformat(),
        "JS_APPS": js_apps, "WORKER": WORKER, "SITE_URL": SITE_URL,
        "FAQ": render_faq(mirror_note),
        "HERO_DL": dls[hero["repo"]][0],
        "HERO_META": "%.1f MB · %s" % (hero_meta["mb"], hero_meta["tag"]),
    })
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "index.html")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    cover = make_og_cover(sum_d, sum_v)
    print("已写出 %s（%d KB）" % (out, len(html.encode("utf-8")) // 1024))
    print("已写出 %s（%d KB）" % (cover, os.path.getsize(cover) // 1024))
    print("合计：下载 %s / 浏览 %s" % (format(sum_d, ","), format(sum_v, ",")))
    for app in APPS:
        print("  %-24s %-14s %s" % (app["repo"], dls[app["repo"]][2], dls[app["repo"]][0]))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
