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

### 1.2 在雨云控制台加 DNS

雨云的域名 → 解析设置（DNS），加下面几条。`@` 表示域名本身，
`www` 是子域。仓库用的 GitHub Pages IP 是固定的四个：

| 主机记录 | 类型 | 记录值 | TTL |
| --- | --- | --- | --- |
| `@` | A | `185.199.108.153` | 600 |
| `@` | A | `185.199.109.153` | 600 |
| `@` | A | `185.199.110.153` | 600 |
| `@` | A | `185.199.111.153` | 600 |
| `www` | CNAME | `xiaimiredmi.github.io` | 600 |

（如果只用子域名，比如 `mtc.example.com`，那就只加一条 CNAME →
`xiaimiredmi.github.io`。）

### 1.3 告诉 GitHub 这个域名

Settings → Pages → **Custom domain** 填你的域名（`www` 或裸域都可以，二选一，
另一个用 301 跳过去）→ Save。等几分钟，**Enforce HTTPS** 勾上就完事。

DNS 生效可以用：

```powershell
Resolve-DnsName mtc-xiaimiredmi.com -Type A
Resolve-DnsName www.mtc-xiaimiredmi.com -Type CNAME
```

> 注意：Pages 的证书是 GitHub 自动签的，DNS 没生效之前勾 HTTPS 会失败，等一会儿再勾。

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
