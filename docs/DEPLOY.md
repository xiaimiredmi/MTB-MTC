# 把站点发布到 mtc-xiaimiredmi 这个域名

站点是**纯静态**的：`site/` 里就是 HTML/CSS/JS 加一个 104 KB 的 `.wasm`。没有后端、
没有数据库、不需要 Node。所以发行只有两件事：把文件放到能对外服务的机器上，把域名的
DNS 指过去。

下面三条路，选一条即可。**只有在没有服务器的情况下才需要看第 1 条。**

| 方案 | 需要什么 | 国内访问速度 | 成本 |
| --- | --- | --- | --- |
| 1. GitHub Pages | 仓库 + 域名 | 一般，`github.io` 偶尔被墙 | 免费 |
| 2. 雨云 VPS + nginx | 服务器 IP、SSH | 好 | 服务器钱 |
| 3. 雨云对象存储 / 静态托管 | 桶 + 域名 | 好 | 按量 |

无论哪条，都先本地确认站点是好的：

```powershell
powershell -ExecutionPolicy Bypass -File site\build.ps1 -Serve
# 打开 http://127.0.0.1:8765/ ，拖一张图，看右边有没有数字
```

---

## 1. GitHub Pages（最省事）

### 1.1 打开 Pages

仓库 → **Settings → Pages → Source: GitHub Actions**。仓库里已经有
`.github/workflows/site.yml`，推一次 `site/` 的改动就会发布。

### 1.2 在雨云控制台加 DNS（`mtc-xiaimiredmi.top`）

雨云 → 域名 → **解析设置**，把下面这些逐条加上。`@` 就是 `mtc-xiaimiredmi.top`
本身，`www` 是它的子域。

| 主机记录 | 类型 | 记录值 | TTL | 说明 |
| --- | --- | --- | --- | --- |
| `@` | A | `185.199.108.153` | 600 | GitHub Pages，四条都要 |
| `@` | A | `185.199.109.153` | 600 | |
| `@` | A | `185.199.110.153` | 600 | |
| `@` | A | `185.199.111.153` | 600 | |
| `@` | AAAA | `2606:50c0:8000::153` | 600 | 可选，IPv6 |
| `@` | AAAA | `2606:50c0:8001::153` | 600 | 可选 |
| `@` | AAAA | `2606:50c0:8002::153` | 600 | 可选 |
| `@` | AAAA | `2606:50c0:8003::153` | 600 | 可选 |
| `www` | CNAME | `xiaimiredmi.github.io` | 600 | 必须是 CNAME，不能是 A |
| `_github-pages-challenge-xiaimiredmi` | TXT | 见下面 1.4 | 600 | 防域名被抢注 |

> 裸域用 A 记录指向 GitHub 的四个 IP；`www` 用 CNAME 指向 `xiaimiredmi.github.io`。
> 两者都配好之后，GitHub 会自动把 `www` 301 跳到裸域（因为 Custom domain 填的是裸域），
> 证书也会同时覆盖两个名字——所以「两个都要能开」是免费的。

### 1.3 告诉 GitHub 这个域名

Settings → Pages → **Custom domain** 一栏填 `mtc-xiaimiredmi.top` → Save。
仓库里也已经放了 `site/CNAME`（内容就是这一行），发布时一起带上去，两边一致。

### 1.4 如果提示域名未验证（Domain unverified）

GitHub 为了防止别人把你的域名抢去当 Pages，会在 Custom domain 下方给一条
**TXT 记录**，形如：

| 主机记录 | 类型 | 记录值 |
| --- | --- | --- |
| `_github-pages-challenge-xiaimiredmi` | TXT | `xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` |

把那串原样加进雨云 DNS，然后回到页面点 **Verify**（点几次都无妨，DNS 需要几分钟）。

### 1.5 等证书，勾 HTTPS

DNS 生效后 GitHub 会自动签发证书（通常几分钟到半小时）。签发完成后
**Enforce HTTPS** 才会变得可勾选，勾上，之后所有 http 自动跳 https。

### 1.6 为什么"直接访问 IP"一定是 404

`185.199.108.153` 这类地址是 GitHub Pages 的**共享入口**，它靠请求头里的 `Host`
判断你要看哪个站点。用浏览器打开 `http://185.199.108.153/`，`Host` 就是那个 IP，
匹配不到任何站点，于是回 404 —— 这是正常的，**不代表部署失败**。

DNS 没生效之前想确认站点已经在了，可以手动带 Host 头：

```powershell
# 站点内容（应为 200）
curl.exe -H "Host: mtc-xiaimiredmi.top" http://185.199.108.153/
# www 应 301 到裸域
curl.exe -o NUL -w "%{http_code}`n" -H "Host: www.mtc-xiaimiredmi.top" http://185.199.108.153/
```

仓库脚本把这件事自动化了：

```powershell
powershell -ExecutionPolicy Bypass -File site\check-domain.ps1 `
  -Base http://185.199.108.153 -HostHeader mtc-xiaimiredmi.top -SkipDns
```

> 另一个坑：域名一旦绑上（Custom domain 已填），`https://<用户名>.github.io/<仓库>/`
> 会 **301 跳到你的域名**。所以在 DNS 生效前，那个地址也打不开——不是坏了，是被重定向了。
> 想先预览，只能临时把 Custom domain 清空。

### 1.7 一条命令确认全部

仓库里有 `site/check-domain.ps1`，它会把该查的都查一遍：四条 A 记录、`www` 的
CNAME、首页能不能拿到、每个静态资源是不是 200、线上 `mtc.wasm` 的字节数是不是和本地
刚构建的一模一样（不一样说明部署是旧的），以及 http 有没有跳到 https。

```powershell
powershell -ExecutionPolicy Bypass -File site\check-domain.ps1
```

它比对的是**哈希**：线上的 `index.html` / `styles.css` / `codec.js` / `app.js` 必须和仓库
里的文件逐字节相同，所以"部署是旧的"这种问题跑一次就露；`mtc.wasm` 则只验 `\0asm`
魔数和量级，因为 workflows 会在 Ubuntu 上**重新编译**它，跨平台产出的字节数本来就会差
几百字节（实测 101 893 vs 本地 104 102）。

全部通过时最后一行是 `all checks passed`，退出码 0。先只验本地也能用：

```powershell
powershell -ExecutionPolicy Bypass -File site\check-domain.ps1 -Base http://127.0.0.1:8765
```

### 1.8 手动确认

```powershell
Resolve-DnsName mtc-xiaimiredmi.top -Type A          # 应返回 185.199.108-111.153
Resolve-DnsName www.mtc-xiaimiredmi.top -Type CNAME  # 应返回 xiaimiredmi.github.io
Invoke-WebRequest https://mtc-xiaimiredmi.top/ -UseBasicParsing | Select-Object StatusCode
Invoke-WebRequest https://mtc-xiaimiredmi.top/mtc.wasm -Method Head -UseBasicParsing | Select-Object StatusCode
```

浏览器打开 https://mtc-xiaimiredmi.top/ ，点「用样图试试」，应看到 MTC ≈ 33.5 KB、
PSNR ≈ 32.57 dB。

> 国内访问 `185.199.*` 有时会被干扰。如果打不开但本地正常，那是线路问题，
> 不是配置问题——这时才需要考虑第 2 条（雨云 VPS）。

---

## 2. 雨云 VPS + nginx（国内速度最好）

假设系统是 Ubuntu 22.04/24.04，且安全组/防火墙放行了 80 和 443。

### 2.1 服务器上装 nginx

```bash
sudo apt update && sudo apt install -y nginx
```

### 2.2 上传站点

从**这台 Windows** 上传（OpenSSH 自带 `scp`）：

```powershell
scp -r site\* root@服务器IP:/var/www/mtc/
```

或者用仓库里的脚本，它先打 tar 再传，比逐个文件快得多：

```powershell
powershell -ExecutionPolicy Bypass -File site\deploy.ps1 -Server 服务器IP -User root
```

### 2.3 nginx 配置

仓库里的 `site/nginx.conf` 可以直接用，改两处域名即可：

```bash
sudo cp /var/www/mtc/nginx.conf /etc/nginx/sites-available/mtc
sudo ln -sf /etc/nginx/sites-available/mtc /etc/nginx/sites-enabled/mtc
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

### 2.4 证书

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d mtc-xiaimiredmi.com -d www.mtc-xiaimiredmi.com
```

certbot 会自动改 nginx 配置并加上续期定时器（`systemctl list-timers | grep certbot` 可查）。

### 2.5 DNS

雨云控制台把 `@` 和 `www` 都指向服务器公网 IP：

| 主机记录 | 类型 | 记录值 |
| --- | --- | --- |
| `@` | A | `服务器公网IP` |
| `www` | A | `服务器公网IP` |

（用 A 记录而不是 CNAME，因为你没有别的域名可指。）

> 国内服务器绑定域名通常需要 **ICP 备案**。没备案的话 80/443 会被云厂商拦截，
> 这一点在雨云控制台会有提示，按提示提交资料即可。

---

## 3. 雨云对象存储 / 静态托管

如果雨云后台提供"静态站点托管"或"对象存储 + CDN"：

1. 先打包：`Compress-Archive site\* mtc-site.zip`
2. 后台上传并解压（或逐个上传），入口文件是 `index.html`
3. 绑定域名时，把 `mtc-xiaimiredmi.com` 填成自定义域名，按后台给的 CNAME 去改 DNS
4. 确保 `mtc.wasm` 以 `application/wasm` 或 `application/octet-stream` 返回都可以——
   页面的加载器不依赖 `instantiateStreaming`，MIME 不对也能跑

---

## 每次更新怎么发

```powershell
powershell -ExecutionPolicy Bypass -File site\build.ps1     # 重新编 wasm 到 site\
git add -A; git commit -m "site: ..."                        # Pages 会自动发布
powershell -ExecutionPolicy Bypass -File site\deploy.ps1 -Server IP   # 或者推到 VPS
```

一个坑：`mtc.wasm` 名字没带版本，浏览器可能缓存旧的那份。更新后如果行为没变，
先强刷（Ctrl+F5）。nginx 配置里已经给 `.wasm` 设了 `Cache-Control: no-cache`。

## 怎么确认真的是你的编解码器在跑

打开站点，点"用样图试试"，应当看到：

- 原始像素 ≈ 562 KB（480×360×3）
- MTC ≈ **33.5 KB**
- PSNR ≈ **32.57 dB**

在命令行对同一张图跑 `mtcodec encode site\assets\sample.png out.mtc -q 85`，
应该是 **34304 字节 / 32.57 dB**。数字一致，说明线上跑的就是仓库里这份 Rust 代码。
