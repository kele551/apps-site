#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 index.html 发布到 Cloudflare Pages（Direct Upload，纯 REST，不需要 node / wrangler）。

谁在调它：
  · GitHub Actions：push 到 main 就自动跑一次（见 .github/workflows/deploy.yml）
  · 本地手动：python tools/deploy_pages.py --apply

环境变量：
  CLOUDFLARE_API_TOKEN  必需。Cloudflare 令牌，权限：Account → Cloudflare Pages → Edit
  CF_ACCOUNT_ID         可选，默认下面的 ACCT
  CF_PAGES_PROJECT      可选，默认 kele551-apps
  CF_PAGES_BRANCH       可选，默认 main（只有等于项目的 production_branch 才占正式域名）
  CF_SKIP_PREFLIGHT     可选。设 1 就跳过「先发预览再提升」，直接发正式（不建议）
  SITE_DIR              可选，默认本脚本所在仓库的根目录

发布顺序（默认，正式发布时）：
  ① 先把页面发到一个预览分支 ci-verify → 轮询就绪 → 回读那个预览地址校验 sha256
  ② 校验通过才用 main 发正式部署 → 再回读生产地址校验一次
  ③ 校验不过就退出非 0，**正式站一个字都不动**
  背景：2026-11-02 出过「四步全 API 成功、线上全 500」的事故，所以必须验证再上生产。

★ 资产键不是文件字节的 blake3，而是：
      blake3( base64(文件内容) + 扩展名(不带点) ).hex()[:32]
  这是 wrangler 的 hashFile。传错不会报错：上传成功、哈希登记成功、部署 stage=success，
  但线上每个资源都取不到（500），日志里没有任何线索。

四步（CF 的 Direct Upload）：
  1) GET  /accounts/<acct>/pages/projects/<proj>/upload-token   返回字段叫 jwt（POST 不行）
  2) POST /pages/assets/upload         JSON: [{key: 资产键, value: base64, metadata: {contentType}, base64: true}]
  3) POST /pages/assets/upsert-hashes  JSON: {"hashes": [资产键, ...]}
  4) POST /accounts/<acct>/pages/projects/<proj>/deployments
          multipart 字段 manifest（{"/index.html": 资产键, "/og-cover.png": 资产键}）+ branch + commit_message
"""
import base64
import hashlib
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request

import blake3

CF = "https://api.cloudflare.com/client/v4"
ACCT = os.environ.get("CF_ACCOUNT_ID") or "5c6f3b8ab0e15624fb719c4fcac6c922"
PROJECT = os.environ.get("CF_PAGES_PROJECT") or "kele551-apps"
BRANCH = os.environ.get("CF_PAGES_BRANCH") or "main"
HERE = os.path.dirname(os.path.abspath(__file__))
SITE_DIR = os.environ.get("SITE_DIR") or os.path.dirname(HERE)
SKIP_PREFLIGHT = (os.environ.get("CF_SKIP_PREFLIGHT") or "") in ("1", "true", "yes")
PREVIEW_BRANCH = "ci-verify"       # 正式发布前的验证分支；它不等于 production_branch，所以不占正式域名
MARKER = "桌面小工具"              # 回读验证用的字符串，页面上必须有
PROD_URL = "https://%s.pages.dev/" % PROJECT


def token():
    t = (os.environ.get("CLOUDFLARE_API_TOKEN") or "").strip()
    if not t:
        raise SystemExit("没有 CLOUDFLARE_API_TOKEN（Actions 里是仓库 secret，本地跑就自己设环境变量）")
    return t


def call(method, path, body=None, auth=None, fields=None, timeout=90):
    """统一发请求。auth 用于资产上传那两步（Bearer JWT），默认用 API 令牌。

    fields: [(name, str)] —— multipart 文本字段（建部署时 manifest 就这么传）。
    返回 (ok, result_or_errors, http_status)
    """
    url = path if path.startswith("http") else CF + path
    headers = {"Authorization": "Bearer " + (auth or token())}
    data = None
    if fields is not None:
        boundary = "----dshpages" + "0" * 10
        buf = []
        for name, value in fields:
            buf.append(("--%s\r\n" % boundary).encode())
            buf.append(('Content-Disposition: form-data; name="%s"\r\n\r\n' % name).encode())
            buf.append(value.encode("utf-8") if isinstance(value, str) else value)
            buf.append(b"\r\n")
        buf.append(("--%s--\r\n" % boundary).encode())
        data = b"".join(buf)
        headers["Content-Type"] = "multipart/form-data; boundary=%s" % boundary
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            j = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "replace")[:1200]
        try:
            j = json.loads(txt)
        except Exception:
            return False, [{"code": e.code, "message": txt[:200]}], e.code
    except Exception as e:
        return False, [{"code": 0, "message": "ERR %s" % e}], 0
    ok = bool(j.get("success"))
    return ok, (j.get("result") if ok else (j.get("errors") or j.get("messages"))), 200


def show_errs(errs):
    if isinstance(errs, list):
        for e in errs:
            print("   ! %s" % (e.get("message") if isinstance(e, dict) else e))
    else:
        print("   !", errs)


def content_type(name):
    guess, _ = mimetypes.guess_type(name)
    return guess or "application/octet-stream"


def asset_hash(name, content):
    """CF Pages 的资产键：blake3(base64(内容) + 扩展名).hex()[:32]（抄 wrangler hashFile）。"""
    ext = os.path.splitext(name)[1][1:]
    return blake3.blake3(base64.b64encode(content) + ext.encode("ascii")).hexdigest()[:32]


def site_files():
    idx = os.path.join(SITE_DIR, "index.html")
    if not os.path.exists(idx):
        raise SystemExit("找不到 %s" % idx)
    with open(idx, "rb") as f:
        html = f.read()
    if MARKER.encode("utf-8") not in html:
        raise SystemExit("index.html 里没有「%s」，不像这个站的页面，停住不动" % MARKER)
    files = [("index.html", html)]
    # 分享封面由 build_page.py 生成；存在就一起上传，缺失时不影响原来的单文件发布。
    for extra in ("og-cover.png",):
        p = os.path.join(SITE_DIR, extra)
        if os.path.exists(p):
            with open(p, "rb") as f:
                files.append((extra, f.read()))
    return files


def get_upload_jwt():
    path = "/accounts/%s/pages/projects/%s/upload-token" % (ACCT, PROJECT)
    ok, res, _ = call("GET", path)
    if ok and isinstance(res, dict):
        for k in ("jwt", "token"):
            if isinstance(res.get(k), str) and res[k]:
                return res[k]
    print("拿不到资产上传 JWT")
    show_errs(res)
    return None


def ensure_project():
    ok, res, _ = call("GET", "/accounts/%s/pages/projects/%s" % (ACCT, PROJECT))
    if ok:
        print("项目 %s（production_branch=%s）" % (res.get("name"), res.get("production_branch")))
        return True
    print("项目 %s 不存在，创建中…" % PROJECT)
    ok, res, _ = call("POST", "/accounts/%s/pages/projects" % ACCT,
                      {"name": PROJECT, "production_branch": BRANCH})
    if not ok:
        print("创建项目失败")
        show_errs(res)
        return False
    return True


def upload_assets(files, jwt):
    """上传文件并登记哈希，返回 {文件名: 资产键}；失败返回 None。"""
    digests = {n: asset_hash(n, c) for n, c in files}
    payload = [{"key": digests[n], "value": base64.b64encode(c).decode("ascii"),
                "metadata": {"contentType": content_type(n)}, "base64": True}
               for n, c in files]
    ok, raw, _ = call("POST", "/pages/assets/upload", body=payload, auth=jwt)
    if not ok:
        print("资产上传失败")
        show_errs(raw)
        return None
    print("已上传 %d 个文件（%d 字节，%s）" % (
        len(files), sum(len(c) for _, c in files),
        "/".join(sorted({content_type(n) for n, _ in files}))))
    ok, res, _ = call("POST", "/pages/assets/upsert-hashes",
                      body={"hashes": sorted(set(digests.values()))}, auth=jwt)
    print("   upsert-hashes %s" % ("通过" if ok else "被拒（继续，部署才是真检验）"))
    if not ok:
        show_errs(res)
    return digests


def create_deployment(digests, branch):
    manifest = {"/" + n: h for n, h in digests.items()}
    msg = os.environ.get("GITHUB_SHA", "")[:8] or time.strftime("%Y-%m-%d %H:%M")
    ok, dep, _ = call("POST", "/accounts/%s/pages/projects/%s/deployments" % (ACCT, PROJECT),
                      fields=[("manifest", json.dumps(manifest)),
                              ("branch", branch),
                              ("commit_message", "落地页 %s（%s）" % (msg, branch))])
    if not ok or not isinstance(dep, dict):
        print("建部署失败（branch=%s）" % branch)
        show_errs(dep)
        return None
    print("部署已提交 [%s] %s → %s" % (branch, dep.get("id"), dep.get("url")))
    return dep


def wait_ready(dep_id, branch):
    for i in range(30):
        time.sleep(4)
        ok, d, _ = call("GET", "/accounts/%s/pages/projects/%s/deployments/%s" % (ACCT, PROJECT, dep_id))
        if not ok:
            show_errs(d)
            return False
        stages = d.get("stages")
        st = ({(s.get("name") or "?"): s.get("status") for s in stages if isinstance(s, dict)}
              if isinstance(stages, list) else
              {k: (v or {}).get("status") for k, v in (stages or {}).items()})
        print("   [%2d] %s %s  latest=%s  file_count=%s" % (
            i + 1, branch, " ".join("%s=%s" % (k, v) for k, v in st.items()),
            (d.get("latest_stage") or {}).get("status"), d.get("file_count")))
        if st.get("deploy") == "success":
            return True
        if "failed" in list(st.values()) or (d.get("latest_stage") or {}).get("status") == "failed":
            print("部署失败：%s" % json.dumps(stages, ensure_ascii=False)[:600])
            return False
    print("轮询 120 秒还没就绪")
    return False


def verify(url, want_sha, tries=6):
    """回读地址：必须 200，且（能比的时候）与本地逐字节一致。"""
    for attempt in range(1, tries + 1):
        if attempt > 1:
            time.sleep(5)
        try:
            with urllib.request.urlopen(urllib.request.Request(
                    url, headers={"User-Agent": "deploy-verify"}), timeout=30) as r:
                body = r.read()
            same = hashlib.sha256(body).hexdigest() == want_sha
            print("   回读 %s → HTTP %s 长度 %d 一致=%s" % (url, r.status, len(body), same))
            if r.status == 200 and same:
                return True
        except Exception as e:
            print("   回读 %s 失败：%s" % (url, e))
    return False


def do_apply():
    files = site_files()
    want = hashlib.sha256(dict(files)["index.html"]).hexdigest()

    if not ensure_project():
        return False
    jwt = get_upload_jwt()
    if not jwt:
        return False
    digests = upload_assets(files, jwt)
    if not digests:
        return False

    # 正式发布：先把同样的资产发到预览分支验证，过了再上生产，坏内容不会见到访客
    if BRANCH == "main" and not SKIP_PREFLIGHT:
        dep = create_deployment(digests, PREVIEW_BRANCH)
        if not dep or not wait_ready(dep.get("id"), PREVIEW_BRANCH):
            print("✘ 预览部署没就绪，正式站一个字都没动")
            return False
        if not verify(dep.get("url"), want):
            print("✘ 预览地址校验不过（可能资产键/清单有问题），正式站一个字都没动")
            return False
        print("✔ 预览校验通过，开始发正式部署")

    dep = create_deployment(digests, BRANCH)
    if not dep or not wait_ready(dep.get("id"), BRANCH):
        return False
    target = PROD_URL if BRANCH == "main" else dep.get("url")
    if not verify(target, want):
        print("✘ 生产地址没通过验证，去控制台把这个部署回滚：dash.cloudflare.com → Pages → %s" % PROJECT)
        return False
    print("✔ 发布成功：%s" % PROD_URL)
    return True


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if "--apply" not in sys.argv:
        print(__doc__)
        sys.exit(0)
    sys.exit(0 if do_apply() else 1)
