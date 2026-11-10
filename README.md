# apps-site —— 作品页源码（自动发布）

海风（kele551）四款 Windows 单文件工具的统一门面页，线上地址：

**https://kele551-apps.pages.dev/**

> 本仓库是**私有**的，只当「发布管道」用；公开的是上面那个网站。仓库不出现在主页列表里，别人打开是 404。

## 自动发布怎么工作

```
改 index.html → git push main → GitHub Actions → Cloudflare Pages（Direct Upload）→ 线上更新
```

- 工作流：`.github/workflows/deploy.yml`
- 发布脚本：`tools/deploy_pages.py`（纯 REST，不需要 node / wrangler）
- 密钥：仓库 Secret `CLOUDFLARE_API_TOKEN`（权限 Account → Cloudflare Pages → Edit）
- 只有 `index.html` / `og-cover.png` / 脚本 / 工作流变动才触发；改 README 不触发。
- 发布末尾会**回读生产地址比对 sha256**，不一致就让这次 Actions 红掉（部署成功不等于能打开）。

## 页面怎么改

页面本体由本地脚本生成（四款 app 的图标、界面截图、数字快照都内联进 `index.html`），
生成器不放进这个仓库（它要读本机各项目的图标路径和 `shots\` 截图）。改法：

1. 在本地 `E:\Qdoer\落地页-样稿\build_page.py` 里改文案 / 链接 / 卡片顺序；
2. 跑 `python build_page.py`。它会：问徽章后端取这次的下载 / 浏览数（取不到时换 shields.io 缓存键再取一次，
   仍失败用 `SNAPSHOT` 兜底）；
   从 GitHub API 读每款最新 tag 与 exe 资产名，自动解析下载直链（见下一节）；
   探 hiwiki 镜像是否真上线，只挂上线的；最后产出 `index.html` 与 1200x630 的 `og-cover.png`；
3. 把 `index.html` 和 `og-cover.png` 一起覆盖到本仓库，`git commit && git push`；
4. Actions 跑完，线上就变了（约 1 分钟）。

`shots\` 里是四款真实界面截图：狐径 / 桌面壁纸 / 热点新闻从各自仓库 `docs/demo/*.mp4` 抽帧，
LIVE直播源用仓库自带的 `docs/screenshot.png`。生成器把它们内联成 webp data URI，
所以 `index.html` 仍是单文件；`og-cover.png` 是唯一额外上传的资产，由发布脚本自动带上。

## 下载直链怎么来的

主按钮不再指向发行版列表页，而是指到 exe 本身，省掉「选版本 → 点附件」两步。
生成器优先拼 `gitcode.com/<owner>/<repo>/releases/download/<tag>/<资产名>`，
探不通再回退 GitHub `releases/latest/download/<资产名>`（并在按钮下如实标注）。

两个实测出来的坑（2026-11-10）：

- GitCode `latest/download/...` 返回的是 HTML 不是文件，必须带 tag；
- 探测只能用 `curl --range 0-0` 这种 1 字节 GET，成功码 `206` +
  `application/octet-stream` 才算真附件。HEAD 会被 GitCode 回 401，
  完整 GET 又会白下 8–15 MB。`--offline` 时不联网，用 `DL_STATIC` 里已实测的链接。

## 一个必须知道的坑

Cloudflare Pages 的资产键**不是**文件字节的 blake3，而是：

```
blake3( base64(文件内容) + 扩展名(不带点) ).hex()[:32]
```

（wrangler 的 `hashFile`）传错不会报错：上传成功、哈希登记成功、部署状态 success，
但线上每个资源都取不到（500）。细节见 `tools/deploy_pages.py` 顶部注释。

## 相关

- 数据口径：下载 = GitHub Releases 附件数 + GitCode 下载统计；浏览 = 各平台 hits.sh 计数合计；
  由 Cloudflare Worker `kele551-badge` 算，页面经 `img.shields.io` 中转取（`*.workers.dev` 在境内被污染）。
- 本地工作副本与档案：`F:\Harness\projects\作品页\`（README / logs / snapshots）。
