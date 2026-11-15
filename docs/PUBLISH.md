# Publishing this repository on GitHub

Step-by-step. Every command is meant to be copy-pasted from the repository root.
中文版在下半部分。

---

## 0. Before you start

| You need | Check |
| --- | --- |
| Git | `git --version` → 2.x |
| A GitHub account | free |
| Either `gh` CLI or a browser | `gh auth status` |
| The repository folder | `D:\MTB-MTC` on Windows, `~/MTB-MTC` on Linux/macOS |

Nothing in this repository is large enough to need Git LFS; the binaries in
`release/` (`MTBViewer.exe` 29 MB, `MTB-MTC-encoder-v1.2.zip` 40 MB —
this one also contains the exe, `MTB-MTC-v1.2.0.zip` 2.8 MB — source + docs
only) are deliberately kept **out of git** and attached to a Release instead.
Keep it that way — GitHub blocks single files above 100 MB, and every clone
would otherwise carry 70 MB of binaries.

Two zips, two purposes:

| File | Contains | For whom |
| --- | --- | --- |
| `release/MTB-MTC-v1.2.0.zip` (2.8 MB) | source, docs, samples, reports — no exe | people who already have Python, or want to read the code |
| `release/MTB-MTC-encoder-v1.2.zip` (40 MB) | the above plus `MTBViewer.exe` | people who just want to open a `.mtb` file on Windows |

Rebuild the small one any time with `python tools/make_release_zip.py`.

---

## 1. What is already in the folder

```text
README.md              English, the landing page
README.zh-CN.md        Chinese
LICENSE                MIT
CHANGELOG.md           version history
.gitignore             excludes build output and binaries
pyproject.toml         pip-installable, provides the `mtcodec` command
requirements.txt       numpy + pillow
docs/FORMAT.md         byte-level container spec (EN + 中文)
docs/CONVERT.md        conversion guide (EN + 中文)
docs/BUILD.md          PyInstaller / Nuitka / Linux / macOS / Android
docs/PUBLISH.md        this file
.github/workflows/release.yml   builds the exe on every version tag
mtcodec/               the codec
deploy/                exe entry point, icon, Windows registration
tools/                 batch convert, build exe, build zip, icon generator,
                       check_release.py, make_release_zip.py
tests/                 plain-python tests
bench/  results/       measurements that back the README tables
samples/               example .mtb / .mtc, alpha and audio included
assets/                icons + the MTB / JPEG / WebP comparison strip
```

---

## 2. Check `.gitignore` before the first commit

It excludes:

```text
__pycache__/  *.py[cod]  build/  dist/  *.egg-info/  .venv/
*.log  _shots/  _shots_report/
release/*.exe  release/*.zip
MTB-MTC-encoder-v*.zip
```

Why: `dist/` is rewritten by every PyInstaller run, and the exe + zip belong to a
Release, not to the source history. If you *want* the binaries in the repository
(for a private repo nobody else clones), delete those two lines and accept the
clone size.

Verify what git would actually take:

```bash
git init -q
git add -A
git status --short | measure            # Windows PowerShell
git status --short | wc -l              # Linux / macOS
du -sh .git                             # should be a few MB, not 70
```

If the exe shows up, the ignore rule is wrong — fix it before committing. Once a
big binary is in history, removing it needs a history rewrite.

---

## 3. First commit

```bash
cd D:\MTB-MTC
git init
git config user.name  "Your Name"
git config user.email "you@example.com"
git add -A
git commit -m "MTB/MTC codec v1.2: image + video container, CLI, viewer, docs"
git branch -M main
```

Line endings: `.gitignore` here does not force `core.autocrlf`. On Windows set

```bash
git config core.autocrlf true
```

so Python sources keep LF in the repository and CRLF locally. The `.txt` notes
with a BOM (`打包与安装说明.txt`) will still be stored as-is; that is fine.

---

## 4. Create the remote

### GitHub Desktop route (no command line)

The folder already has `.git` and one commit, so Desktop treats it as a real
repository:

1. `File → Add local repository` (文件 → 添加本地仓库), choose `D:\MTB-MTC`.
   If Desktop was already open on the folder and showed *"this folder does not
   appear to be a valid Git repository"*, close that dialog and open it again —
   it cached the earlier state.
2. The repository appears on the left with branch `main` and "no local changes".
3. Click **Publish repository** (发布仓库) in the top bar → choose **Public** →
   keep the name `MTB-MTC` → Publish.

That creates the GitHub repository, adds `origin` and pushes `main` in one step.
Then make the first release: `Releases → Draft a new release` on GitHub, tag
`v1.2.0`, drag `release/MTBViewer.exe` and the two zips into the attachments box.

Note: Desktop shows "Publish repository" only for a repo with no remote. If you
already published once, use **Repository → Push** after committing.

### Browser route

1. <https://github.com/new>
2. Repository name: `MTB-MTC` (description: `Pure-Python image (.mtb) and video (.mtc) codec`)
3. **Public**, and **do not** tick "Add a README" — you already have one
4. Create, then copy the HTTPS URL

### CLI route

```bash
gh auth login
gh repo create MTB-MTC --public --source=. --remote=origin --push
```

That single `gh repo create` line does steps 4 and 5 for you. Skip to section 6.

---

## 5. Push

```bash
git remote add origin https://github.com/<user>/MTB-MTC.git
git push -u origin main
```

SSH variant:

```bash
git remote add origin git@github.com:<user>/MTB-MTC.git
git push -u origin main
```

If the push is rejected because the remote already has commits (you ticked
"Add a README"), merge instead of force-pushing:

```bash
git pull --rebase origin main
git push -u origin main
```

---

## 6. Tag and publish a Release

The tag is what makes the repo look finished: GitHub shows "Releases" on the
landing page, and the CI workflow in `.github/workflows/release.yml` fires.

```bash
git tag -a v1.2.0 -m "v1.2.0: alpha plane, fps + embedded audio, size presets, batch convert"
git push origin v1.2.0
```

Then attach the binaries. CLI:

```bash
gh release create v1.2.0 \
    --title "MTB/MTC v1.2.0" \
    --notes-file CHANGELOG.md \
    release/MTBViewer.exe \
    release/MTB-MTC-encoder-v1.2.zip \
    release/MTB-MTC-v1.2.0.zip
```

Browser:

1. Repository → **Releases** → **Draft a new release**
2. Choose tag `v1.2.0`, title `MTB/MTC v1.2.0`
3. Paste the top section of `CHANGELOG.md`
4. Drag `release/MTBViewer.exe`, `release/MTB-MTC-encoder-v1.2.zip` and
   `release/MTB-MTC-v1.2.0.zip` into the attachments box
5. Publish

Release notes should say what a visitor needs to know in ten seconds:

```text
Windows: download MTBViewer.exe, double-click a .mtb / .mtc file.
Other platforms: pip install -r requirements.txt, then
  python -m mtcodec convert photo.png photo.mtb
  python -m mtcodec convert clip.mp4 clip.mtc
Full docs: docs/CONVERT.md
```

---

## 7. GitHub Actions

`.github/workflows/release.yml` runs on every `v*` tag push:

1. checkout
2. Python 3.12
3. `pip install -r requirements.txt pyinstaller`
4. run `tests/test_codec.py` and `tests/test_formats.py`
5. `python tools/build_exe.py`
6. upload `dist/MTBViewer.exe` as a workflow artifact

Use it as a sanity check: if the tag build fails, the release is broken.
The artifact is downloadable from the Actions run page; a maintainer with a
Windows machine still has to attach it to the Release, or add `gh release upload`
to the workflow with a token.

If the Windows runner reports `Can't find a usable init.tcl`, swap the
`actions/setup-python` step for a plain `python.org` installer step — the CI
Python usually has Tk, but not always.

---

## 8. The update loop

Every future version:

```bash
# 1. code
python tests/test_codec.py && python tests/test_formats.py
python bench/run_convert.py            # refresh results/ if numbers moved
python tools/check_release.py          # docs links, config, ignore rules

# 2. version bump: pyproject.toml + CHANGELOG.md + TOP in tools/make_release_zip.py
# 3. build the binary and the two zips
python tools/build_exe.py
python tools/make_release_zip.py       # release/MTB-MTC-v<ver>.zip
python tools/make_zip.py               # the 40 MB bundle that includes the exe

# 4. commit and tag
git add -A
git commit -m "v1.3.0: <one line>"
git tag -a v1.3.0 -m "v1.3.0"
git push origin main --tags

# 5. release
gh release create v1.3.0 --title "MTB/MTC v1.3.0" --notes-file CHANGELOG.md \
    release/MTBViewer.exe release/MTB-MTC-encoder-v1.3.zip release/MTB-MTC-v1.3.0.zip
```

Keep `pyproject.toml`'s `version`, the CHANGELOG heading, the tag name and the
zip file name in sync. Mismatched version strings are the most common release bug.

---

## 9. Problems you will hit

| Problem | Cause | Fix |
| --- | --- | --- |
| `file is 100.00 MB; this exceeds GitHub's file size limit` | binariy tracked | remove it from the index, add to `.gitignore`, attach to Release |
| exe shows up in `git status` | ignore rule missing or path differs | `git rm --cached release/MTBViewer.exe` |
| Chinese file names render as `?????` | terminal encoding, not git | `git config i18n.commitEncoding utf8`; the files themselves are stored correctly |
| every file shows as modified | line endings | `git config core.autocrlf true`, then `git add -A` |
| `Updates were rejected` | remote has commits | `git pull --rebase origin main` |
| tag already exists | re-tagging | `git tag -d v1.2.0 && git push origin :refs/tags/v1.2.0` then re-tag |
| Actions fails on `init.tcl` | CI Python without Tk | use python.org installer in the workflow |
| README images broken on GitHub | relative to the wrong folder | from `README.md`, paths are relative to the repo root (`assets/compare.png` is correct) |

---

## 10. Repository polish (optional, 5 minutes)

* **About**: description `Pure-Python image (.mtb) and video (.mtc) codec with alpha, embedded audio and lossless round-trip`, website blank, topics `python codec image-compression video-codec`.
* **Social preview**: Settings → Social preview → upload `assets/compare.png` (1280×640 crop).
* **Topics**: `python`, `image-codec`, `video-codec`, `numpy`, `pillow`, `dct`, `arithmetic-coding`.
* **Pin the docs**: `docs/` is already linked from both READMEs; GitHub renders the tables and the code fences fine.
* **Languages**: add `README.zh-CN.md` as a link at the top, already done.
* Do **not** enable "Issues" you will not answer; a project with silent issues
  looks worse than one with none.

---

# 中文版

## 0. 开始之前

| 需要 | 检查 |
| --- | --- |
| Git | `git --version` → 2.x |
| GitHub 账号 | 免费 |
| `gh` 命令行或浏览器 | `gh auth status` |
| 仓库目录 | Windows 是 `D:\MTB-MTC` |

这个仓库没有大到要上 Git LFS 的东西。`release/` 里的二进制
（`MTBViewer.exe` 29 MB、`MTB-MTC-encoder-v1.2.zip` 40 MB——这个里面也带 exe、
`MTB-MTC-v1.2.0.zip` 2.8 MB——只有源码和文档）是**故意不入 git** 的，放
Release 附件里。GitHub 单文件上限 100 MB，而且一旦入库，别人每次 clone 都要拖
70 MB 二进制。

两个 zip，两种用途：

| 文件 | 内容 | 给谁 |
| --- | --- | --- |
| `release/MTB-MTC-v1.2.0.zip`（2.8 MB） | 源码、文档、样例、报告，不含 exe | 已经装了 Python 的人，或者想读代码的人 |
| `release/MTB-MTC-encoder-v1.2.zip`（40 MB） | 上面那些再加 `MTBViewer.exe` | 只想在 Windows 上双击打开 `.mtb` 的人 |

小包随时可用 `python tools/make_release_zip.py` 重打。

## 1. 目录里已经有什么

```text
README.md              英文，仓库门面
README.zh-CN.md        中文
LICENSE                MIT
CHANGELOG.md           版本历史
.gitignore             排除构建产物与二进制
pyproject.toml         可 pip 安装，提供 `mtcodec` 命令
requirements.txt       numpy + pillow
docs/FORMAT.md         字节级容器规范（英 + 中）
docs/CONVERT.md        转换指南（英 + 中）
docs/BUILD.md          PyInstaller / Nuitka / Linux / macOS / 安卓
docs/PUBLISH.md        本文件
.github/workflows/release.yml   每次打 tag 自动构建 exe
mtcodec/               编解码器
deploy/                exe 入口、图标、Windows 关联注册
tools/                 批量转换、打 exe、打 zip、图标生成、
                       check_release.py、make_release_zip.py
tests/                 纯 python 测试
bench/  results/       支撑 README 表格的实测
samples/               示例 .mtb / .mtc，含透明与音轨
assets/                图标 + MTB / JPEG / WebP 对比条
```

## 2. 第一次提交前先看 `.gitignore`

它排除：

```text
__pycache__/  *.py[cod]  build/  dist/  *.egg-info/  .venv/
*.log  _shots/  _shots_report/
release/*.exe  release/*.zip
MTB-MTC-encoder-v*.zip
```

原因：`dist/` 每次 PyInstaller 都会重写，exe 和 zip 属于 Release 附件，不属于
源码历史。如果你**就想**把二进制放进仓库（私有仓库、别人不 clone），删掉那
两行，然后接受 clone 体积变大。

先确认 git 到底会收哪些文件：

```bash
git init -q
git add -A
git status --short | measure        # Windows PowerShell
du -sh .git                          # 应该是几 MB，不是 70 MB
```

exe 出现在列表里，说明忽略规则写错了，提交前修好。大二进制一旦进了历史，
想删就得重写历史。

## 3. 第一次提交

```bash
cd D:\MTB-MTC
git init
git config user.name  "你的名字"
git config user.email "you@example.com"
git add -A
git commit -m "MTB/MTC codec v1.2: image + video container, CLI, viewer, docs"
git branch -M main
```

换行符：`.gitignore` 不强制 `core.autocrlf`。Windows 上建议

```bash
git config core.autocrlf true
```

这样仓库里 Python 源码是 LF，本地是 CRLF。带 BOM 的 `打包与安装说明.txt`
会原样存储，没有影响。

## 4. 创建远程仓库

### GitHub Desktop 路线（不用命令行）

目录里已经有 `.git` 和一个提交，Desktop 会把它当成正常仓库：

1. `文件 → 添加本地仓库`，选中 `D:\MTB-MTC`。如果 Desktop 还停在那句"这个文件夹
   似乎不是一个有效的 Git 仓库"的弹窗上，先关掉再重新打开——它缓存了旧状态。
2. 左侧出现仓库，分支 `main`，"本地没有发生变化"。
3. 点顶栏 **发布仓库（Publish repository）** → 选 **Public** → 名字保持
   `MTB-MTC` → 发布。

这一步就把 GitHub 仓库建好、加上 `origin`、把 `main` 推上去。然后到 GitHub 上
`Releases → Draft a new release`，tag 填 `v1.2.0`，把 `release/MTBViewer.exe`
和两个 zip 拖进附件框。

注意：Desktop 只在"还没有远程"时显示"发布仓库"。发布过之后再提交，用
**Repository → Push**。

### 网页法

1. <https://github.com/new>
2. 仓库名 `MTB-MTC`，描述 `Pure-Python image (.mtb) and video (.mtc) codec`
3. 选 **Public**，**不要**勾"Add a README"——你已经有 README
4. 创建，复制 HTTPS 地址

### 命令行法

```bash
gh auth login
gh repo create MTB-MTC --public --source=. --remote=origin --push
```

这一行就把第 4、5 步都做完了，可以直接跳到第 6 节。

## 5. 推送

```bash
git remote add origin https://github.com/<user>/MTB-MTC.git
git push -u origin main
```

SSH 写法：

```bash
git remote add origin git@github.com:<user>/MTB-MTC.git
git push -u origin main
```

如果因为远程已有提交被拒绝（你不小心勾了"Add a README"），用合并而不是强推：

```bash
git pull --rebase origin main
git push -u origin main
```

## 6. 打 tag、发 Release

tag 是让仓库"看起来做完了"的关键：GitHub 首页会显示 Releases，
`.github/workflows/release.yml` 也会被触发。

```bash
git tag -a v1.2.0 -m "v1.2.0: alpha plane, fps + embedded audio, size presets, batch convert"
git push origin v1.2.0
```

然后挂二进制。命令行：

```bash
gh release create v1.2.0 --title "MTB/MTC v1.2.0" --notes-file CHANGELOG.md release/MTBViewer.exe release/MTB-MTC-encoder-v1.2.zip release/MTB-MTC-v1.2.0.zip
```

网页：

1. 仓库 → **Releases** → **Draft a new release**
2. 选 tag `v1.2.0`，标题 `MTB/MTC v1.2.0`
3. 把 `CHANGELOG.md` 顶部那段贴进说明
4. 把 `release/MTBViewer.exe`、`release/MTB-MTC-encoder-v1.2.zip`、
   `release/MTB-MTC-v1.2.0.zip` 拖进附件框
5. 发布

说明里应该写清楚"十秒钟内能看懂"的东西：

```text
Windows：下载 MTBViewer.exe，双击 .mtb / .mtc 文件。
其他平台：pip install -r requirements.txt
  python -m mtcodec convert 照片.png 照片.mtb
  python -m mtcodec convert 片子.mp4 片子.mtc
完整文档：docs/CONVERT.md
```

## 7. GitHub Actions

`.github/workflows/release.yml` 在每次 `v*` tag 推送时跑：

1. checkout
2. Python 3.12
3. `pip install -r requirements.txt pyinstaller`
4. 跑 `tests/test_codec.py`、`tests/test_formats.py`
5. `python tools/build_exe.py`
6. 把 `dist/MTBViewer.exe` 作为 workflow artifact 上传

把它当"体检"用：tag 构建失败，说明这次发布是坏的。
产物可以在 Actions 运行页面下载；要自动挂到 Release，需要加一个带 token 的
`gh release upload` 步骤。

如果 Windows runner 报 `Can't find a usable init.tcl`，把 `actions/setup-python`
换成直接装 python.org 安装包的步骤——CI 的 Python 通常带 Tk，但不是总有。

## 8. 以后每次更新的循环

```bash
# 1. 改代码
python tests/test_codec.py && python tests/test_formats.py
python bench/run_convert.py            # 数字变了就刷新 results/
python tools/check_release.py          # 文档链接、配置、忽略规则自检

# 2. 改版本号：pyproject.toml + CHANGELOG.md + make_release_zip.py 里的 TOP
# 3. 打包
python tools/build_exe.py
python tools/make_release_zip.py       # release/MTB-MTC-v<版本>.zip
python tools/make_zip.py               # 带 exe 的那个 40 MB 包

# 4. 提交与打 tag
git add -A
git commit -m "v1.3.0: <一句话>"
git tag -a v1.3.0 -m "v1.3.0"
git push origin main --tags

# 5. 发版
gh release create v1.3.0 --title "MTB/MTC v1.3.0" --notes-file CHANGELOG.md release/MTBViewer.exe release/MTB-MTC-encoder-v1.3.zip release/MTB-MTC-v1.3.0.zip
```

让 `pyproject.toml` 的 `version`、CHANGELOG 标题、tag 名、zip 文件名保持一致。
版本号对不上是最常见的发布事故。

## 9. 一定会遇到的问题

| 现象 | 原因 | 解决 |
| --- | --- | --- |
| `file is 100.00 MB; this exceeds GitHub's file size limit` | 二进制被跟踪了 | 从索引里删掉，加进 `.gitignore`，挂到 Release |
| `git status` 里出现 exe | 忽略规则缺失或路径不对 | `git rm --cached release/MTBViewer.exe` |
| 中文文件名显示成 `?????` | 终端编码问题，不是 git | `git config i18n.commitEncoding utf8`；文件本身存得没问题 |
| 所有文件都显示已修改 | 换行符 | `git config core.autocrlf true`，然后 `git add -A` |
| `Updates were rejected` | 远程已有提交 | `git pull --rebase origin main` |
| tag 已存在 | 重复打 tag | `git tag -d v1.2.0 && git push origin :refs/tags/v1.2.0` 再重打 |
| Actions 卡在 `init.tcl` | CI 的 Python 没有 Tk | 在 workflow 里改用 python.org 安装包 |
| GitHub 上 README 图片裂了 | 相对路径算错 | 在根目录 `README.md` 里写 `assets/compare.png` 就对 |

## 10. 仓库打磨（可选，5 分钟）

* **About**：描述 `Pure-Python image (.mtb) and video (.mtc) codec with alpha, embedded audio and lossless round-trip`，topics 填 `python codec image-compression video-codec`。
* **社交预览**：Settings → Social preview → 上传 `assets/compare.png`（裁 1280×640）。
* **Topics**：`python`、`image-codec`、`video-codec`、`numpy`、`pillow`、`dct`、`arithmetic-coding`。
* **文档**：两份 README 都已经链到 `docs/`，GitHub 能正常渲染表格和代码块。
* **语言**：`README.zh-CN.md` 已在顶部互相链接。
* **不要**开 Issues 又不回；一个没人理的 Issues 页比没有更难看。
