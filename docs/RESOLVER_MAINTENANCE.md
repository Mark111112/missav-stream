# MissAV Resolver Maintenance Guide

本文档面向未来维护 `missav-stream` 的开发者，重点说明：

- 当前解析器的工程思路
- 源站变化时如何定位问题
- 应优先修改哪一层代码
- 如何以较低风险扩展而不是盲目重写

---

## 1. 先理解：当前服务不是“解密器”

`missav-stream` 当前更接近一个：

> **页面模式识别器 + HLS 地址整理器**

它主要做三件事：

1. **伪装成浏览器获取影片页 HTML**
2. **从 HTML / script / video 标签中提取视频线索**
3. **把线索整理成最终可返回的 HLS 地址**

它通常并不需要真正“解密视频”。
很多时候所谓“加密方法变化”，实际更常见的是：

- 页面嵌入方式改了
- UUID / m3u8 出现位置变了
- script 里的变量名变了
- playlist 结构变了
- 播放时附加上下文要求变了（Referer / Origin / 浏览器态）

因此排障时，不要先假设“密码学解密逻辑坏了”，而要先判断是哪一层变了。

---

## 2. 当前代码分层

### 2.1 API 包装层：`app.py`

`app.py` 很薄，主要负责：

- 暴露 `/api/resolve/<movie_id>` 与 `/api/resolve` POST 接口
- 调用 `resolver.resolve(...)`
- 把结果包装成统一 `playback` 结构

它本身通常不是脆弱点。
除非后续你要调整返回协议，否则大多数“源站变化”问题都不在这一层。

### 2.2 页面获取层：`resolver._fetch_with_curl_cffi()` / `_fetch_with_requests()`

职责：

- 拿到影片详情页 HTML
- 处理 Cloudflare / 403 / 伪装浏览器版本回退

这层如果失效，后面所有解析都会失效。

### 2.3 元数据提取层：`resolver._extract_metadata()`

职责：

- 从页面 HTML 中提取：
  - UUID
  - 直接 m3u8 URL
  - video src
  - script 中的特殊编码格式

这是**当前最脆弱的一层**。

### 2.4 Playlist 获取与质量选择层：`_fetch_playlist()` / `_parse_playlist()`

职责：

- 从 `playlist.m3u8` 获取主列表
- 解析不同清晰度
- 选择最终要返回的流地址

这层依赖 HLS 结构和源站的目录规则。如果站点改了 playlist 格式或路径命名，也可能在这里失效。

### 2.5 播放上下文层：客户端 / headers

当前 `missav-stream` 返回：

- `direct_url`
- `headers`（Referer / Origin / User-Agent）

这层解决的是：

> **地址虽然拿到了，但播放时需要额外上下文**

如果这里不对，常见现象是：

- 解析成功
- 但客户端播放失败 / 403 / manifestLoadError

---

## 3. 排障时的标准故障树

每次出问题时，先只回答下面 4 个问题：

1. **页面拿到了吗？**
2. **元数据提出来了吗？**
3. **playlist 拿到了吗？**
4. **播放时附加上下文带对了吗？**

不要一上来就说“加密变了”。

---

## 4. 四类常见故障与对应修改点

### 类型 A：页面拿不到

典型现象：

- 返回 403
- 日志里连续出现 `curl_cffi (...) 请求返回 403`
- 或直接 timeout / challenge 页面

优先检查：

- `resolver._fetch_with_curl_cffi()`
- `resolver._fetch_with_requests()`
- `DEFAULT_HEADERS`
- `impersonate_versions`

处理思路：

1. 先确认真实浏览器是否能打开该影片页
2. 如果浏览器能打开而服务端拿不到：
   - 更新 `curl_cffi`
   - 调整 `impersonate` 版本优先级
   - 微调 headers / cookies
3. 如果站点明显更依赖真实浏览器态：
   - 不要无限堆 header
   - 考虑引入浏览器辅助 fallback

### 类型 B：页面拿到了，但元数据提不出来

典型现象：

- 请求返回 200
- 但日志里出现：`无法提取视频元数据`

优先检查：

- `MATCH_PATTERNS`
- `_extract_metadata()`

处理思路：

1. 保存当前影片页 HTML 样本
2. 搜索这些关键词：
   - `surrit`
   - `m3u8`
   - `playlist`
   - `video`
   - UUID 形状
3. 判断新的嵌入方式属于哪种：
   - 仍然是字符串模式变化 → 新增 pattern
   - 变成 JSON / state → 优先 parse JSON，不要只堆 regex
   - 变成 JS 动态计算 → 可能需要浏览器执行后提取

重要原则：

> 优先新增兼容分支，不要轻易删掉旧 pattern。

站点可能会在不同页面/时期并存多种嵌入方式。

### 类型 C：UUID 提出来了，但 playlist/清晰度逻辑失效

典型现象：

- 日志里能看到 UUID
- 但后面出现：
  - `无法获取播放列表内容，返回主列表 URL`
  - 或只能返回 master playlist
  - 或选不到目标清晰度

优先检查：

- `_fetch_playlist()`
- `_parse_playlist()`
- `RESOLUTION_PATTERN`
- 清晰度路径命名假设

处理思路：

1. 先区分：
   - 是拿不到 playlist
   - 还是拿到了但解析错了
2. 如果拿不到：
   - 看请求头 / Referer / Origin / 签名参数 / URL 规则
3. 如果拿到了但解析错：
   - 解析 `#EXT-X-STREAM-INF`
   - 优先按 HLS 协议选流，而不是只按目录名猜

工程建议：

未来如果要增强健壮性，优先把 `_parse_playlist()` 改成：

1. 解析 `EXT-X-STREAM-INF`
2. 记录下一行 URI
3. 按 `RESOLUTION` / `BANDWIDTH` 选流

而不是只依赖：

- `1080p/video.m3u8`
- `1920x1080/video.m3u8`

### 类型 D：地址拿到了，但播放失败

典型现象：

- 服务端日志显示解析成功
- 客户端播放却失败
- 例如 403 / manifestLoadError / 黑屏

这通常不是 resolver 解析层问题，而是：

- Referer 不对
- Origin 不对
- 客户端没把 headers 带上
- 源站要求更完整的浏览器上下文

优先检查：

- `app.py` 返回的 `playback.headers`
- 客户端是否真的按 `headers` 播放
- 是否需要切换到本地 proxy 模式

---

## 5. 源站变化时，建议的工作顺序

### 第一步：留样本

每次失效都尽量保存这三类东西：

1. **影片页 HTML**
2. **playlist 内容**（如果请求得到）
3. **最终 API 返回 JSON**

如果没有样本，下次排障就只能靠猜。

### 第二步：定位层级

按下面顺序判断：

1. fetch page
2. extract metadata
3. fetch playlist
4. parse playlist
5. playback context

### 第三步：局部修改

不要把整个 resolver 推倒重来。
先看是不是只需要：

- 新增一个 pattern
- 调整一个 fetch fallback
- 兼容一种新的 playlist 结构
- 修改 headers 返回策略

---

## 6. 推荐的日志与失败码思路

当前日志已经能用，但未来建议逐步标准化为以下失败码：

- `page_fetch_failed`
- `metadata_not_found`
- `playlist_fetch_failed`
- `playlist_parse_failed`
- `playback_context_required`

这样以后只看日志就能快速知道该改哪一层。

---

## 7. 真正的边界：什么时候不该继续硬改 resolver

如果未来站点变化只是：

- 页面模式变了
- script 结构变了
- playlist 规则变了

那么这套 resolver 仍然值得维护。

但如果站点开始强依赖：

- 短时签名
- 强会话绑定
- 浏览器验证态
- DRM / EME / Widevine

那就要意识到：

> 当前轻量解析方案已经接近边界。

此时更合理的方向通常是：

- 浏览器辅助获取真实播放请求
- 本地 proxy / session 复用
- 重新定义项目边界，而不是继续堆更多 regex

---

## 8. 如果遇到 challenge / 验证码，工程思路是什么？

先区分两类问题：

### 8.1 页面 challenge / 验证码

典型现象：

- 影片页本身拿不到
- 返回 Cloudflare challenge / Turnstile / 人机验证页
- 需要执行 JS 后才能继续

这类问题的重点不是“怎么解析内容”，而是：

> **怎么先进入页面**

建议顺序：

1. **先提升浏览器拟态**
   - 更新 `curl_cffi`
   - 调整 `impersonate` 版本优先级
   - 微调 headers / cookies
2. **如果拟态仍不够，考虑浏览器辅助模式**
   - Playwright / 有头浏览器
   - 让浏览器真实执行 challenge
   - 复用 cookies / session
3. **如果出现明确验证码**
   - 优先考虑“人工通过一次 + 复用会话”
   - 或“浏览器常驻 + 会话复用”

工程上不要优先追求“自动识别验证码”，因为：

- 成本高
- 稳定性差
- 站点一变又得重来

更现实的工程策略通常是：

> **人工通过一次，系统复用验证后的浏览器态 / session**

### 8.2 播放链路 challenge

典型现象：

- 页面能开
- UUID / m3u8 也能拿到
- 但请求 `playlist.m3u8` / `video.m3u8` / 分片时被拦

这类问题的重点不是“怎么进入页面”，而是：

> **怎么复现真实播放请求上下文**

建议顺序：

1. 先试最轻量的上下文补齐
   - `Referer`
   - `Origin`
   - `User-Agent`
2. 如果客户端层不稳定，就改本地 proxy
   - m3u8 改写
   - 分片继续走代理
3. 如果播放请求强依赖浏览器 session
   - 让真实浏览器播放一次
   - 抓真实播放请求中的 cookies / headers / token

### 8.3 什么时候说明项目边界变了

如果未来站点升级到：

- 高频验证码
- 强行为验证
- 强 session 绑定
- DRM / EME / Widevine

那不要再默认“继续堆 resolver 就能解决”。

这时更合理的方向通常是：

- 浏览器辅助模式
- 本地 proxy + session 复用
- 接受人工介入
- 明确轻量解析方案的边界

一句话：

> 普通页面结构变化，优先改 resolver；  
> challenge / 验证码，优先改取页面方式与浏览器态；  
> 真正 DRM / 强权限机制，说明项目边界已经上移。

---

## 9. 建议的工程增强项

### 9.1 给 resolver 增加 fixture 测试

保存几份真实 HTML / playlist 样本，写单测：

- 输入样本 HTML
- 断言应该提取出哪个 UUID / m3u8

这样站点变化后，你能快速知道是哪个 pattern 先失效。

### 9.2 拆分 `_extract_metadata()`

后续可拆成更清晰的子函数，例如：

- `extract_from_pipe()`
- `extract_from_surrit_url()`
- `extract_from_video_src()`
- `extract_from_generic_m3u8()`

便于逐个维护，而不是把所有逻辑堆在一个函数里。

### 9.3 优先结构化解析，少堆 regex

如果页面里存在结构化 JSON / state，优先 parse 它。  
Regex 应更多作为兼容层，而不是唯一方案。

### 9.4 提高 playlist 解析的协议意识

优先按 HLS 语义（`EXT-X-STREAM-INF`）选流，少依赖当前站点目录命名习惯。

---

## 10. 维护者的最简判断准则

当源站又变了时，先问自己：

> 它是“页面线索变了”，还是“播放权限机制变了”？

- 如果是**页面线索变了** → 优先改 resolver
- 如果是**播放权限机制变了** → 优先改 headers / proxy / browser fallback
- 如果是**真正 DRM / 强会话绑定** → 说明这套轻量方案已接近边界

---

## 11. 与 busweb / 客户端的分工

当前推荐分工：

- `missav-stream`
  - 轻量解析
  - 返回 `direct_url + headers`
- `busweb`
  - 本地高带宽环境可做重代理
  - 返回 `proxy_path`
- 客户端
  - 优先消费 `proxy`
  - 否则消费 `headers`

因此，未来不要把所有问题都往 `missav-stream` 里塞。
有些问题本质上应该由：

- busweb proxy
- 客户端 headers
- 浏览器态 fallback

来解决。
