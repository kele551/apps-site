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
- 只有 `index.html` / 脚本 / 工作流变动才触发；改 README 不触发。
- 发布末尾会**回读生产地址比对 sha256**，不一致就让这次 Actions 红掉（部署成功不等于能打开）。

## 页面怎么改

页面本体由本地脚本生成（四款 app 的图标、实时数字快照都内联进去），生成器不放进这个仓库
（它要读本机各项目的图标路径）。改法：

1. 在本地 `E:\Qdoer\落地页-样稿\build_page.py` 里改文案 / 链接 / 卡片顺序；
2. 跑 `build_page.py` 生成新的 `index.html`；
3. 把新的 `index.html` 覆盖到本仓库，`git commit && git push`；
4. Actions 跑完，线上就变了（约 1 分钟）。

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
