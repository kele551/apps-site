# 落地页生成器（源码存档）

生成根目录 `index.html` 与 `og-cover.png` 的完整代码，随仓库做版本备份。

> **日常活版本仍是 `E:\Qdoer\落地页-样稿\build_page.py`。**
> 改页面请改那边，生成后把 `index.html` + `og-cover.png` 覆盖到仓库根目录再 push。
> 本目录是同步过来的副本，只改这里不会自动上线；两边要保持一致。

## 目录

- `build_page.py` — 生成器，单文件，Python 3 + Pillow
- `shots/` — 四款真实界面截图 webp，来源与裁剪参数见 `shots/README.txt`
- `icons/` — 四款 logo，各项目 `docs/icon.png` 的副本

## 跑一次

```bash
python build_page.py --offline   # 不联网，用内置快照与静态直链，产物写在本目录
python build_page.py             # 联网取实时数 + 解析下载直链 + 探 hiwiki 镜像
```

**产物默认写在脚本所在目录（即本目录），不会覆盖仓库根目录的发布文件。**
需要写到别处用 `PAGE_OUT_DIR=/some/dir python build_page.py --offline`。

## 环境变量（覆盖默认路径）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `PAGE_OUT_DIR` | 脚本所在目录 | `index.html` / `og-cover.png` 输出位置 |
| `PAGE_SHOTS_DIR` | `<OUT_DIR>/shots` | 界面截图 |
| `PAGE_ICONS_DIR` | `<OUT_DIR>/icons` | 图标副本，本机项目图标找不到时回退到这里 |
| `PAGE_REPO_ROOT` | `F:\Harness\projects` | 本机各项目源码根目录 |
| `PAGE_FONT` | `C:\Windows\Fonts\msyh.ttc` | 封面字体，非 Windows 需指定支持中文的字体 |

## 依赖与注意

- Python 3.9+、`pip install Pillow`；联网模式还要本机有 `curl`（探测直链用 1 字节 range GET）。
- 数字来自 `kele551-badge` Worker，经 `img.shields.io` 中转（5 分钟缓存）；
  失败时换缓存键只重试一次，仍失败用 `SNAPSHOT` 兜底并在页面标注日期。
- 直链与探测的两个坑见根目录 `README.md`「下载直链怎么来的」。
