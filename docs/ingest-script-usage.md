# Ingest Script Usage

当前提供了一个最小可用的入库脚本：`ingest_wechat_article.py`。

## 能力范围

- 支持从 `--url`、`--url-list` 或 `--html-file` 输入文章
- 自动抽取标题、发布日期、正文文本
- 自动提取并下载正文图片到 `images/`
- 基于启发式规则初步判断 `content_type`
- 自动预填 `summary`、`research_question`、`core_hypothesis`、`signal_framework`
- 自动提取 HTML 中的 `pre/code` 代码块并写入 `Code Blocks`
- 按模板生成 `article.md`
- 同时落地 `raw.html`、`source.json` 和 `images/` 目录
- 批量模式会自动清洗空行、中文分号和重复链接
- 如果公众号返回验证页，会直接报错而不是生成空文档

## 当前限制

- OCR 还没有接入
- `idea_blocks` 等启发型字段仍需后续接 LLM 生成
- `content_type` 是启发式分类，不是最终结果
- `summary`、`research_question` 等字段目前是规则预填，不是语义级理解
- 对公众号页面结构变化的鲁棒性有限
- 图片下载失败时会在文档里写注释占位，不会中断整篇入库
- 有些公众号链接会被微信风控拦截，这时脚本无法直接绕过
- 代码块只能提取 HTML 原生 `pre/code`，图片里的代码还需要 OCR

## 依赖

建议先安装：

```bash
pip install requests beautifulsoup4
```

## 用法

导入单个 URL：

```bash
python ingest_wechat_article.py --url "https://mp.weixin.qq.com/s/xxxxx"
```

批量导入 URL 列表：

```bash
python ingest_wechat_article.py --url-list "D:\\work\\research\\knowledge base\\url list.txt"
```

如果工作区根目录存在默认文件 `url list.txt`，也可以直接运行：

```bash
python ingest_wechat_article.py
```

从本地 HTML 入库：

```bash
python ingest_wechat_article.py --html-file "D:\\path\\to\\article.html"
```

只做解析预览，不写文件：

```bash
python ingest_wechat_article.py --url-list "D:\\work\\research\\knowledge base\\url list.txt" --dry-run
```

手动覆盖分类：

```bash
python ingest_wechat_article.py --url-list "D:\\work\\research\\knowledge base\\url list.txt" --content-type allocation
```

## URL 列表格式

每行一个链接，允许有空行，行尾也允许中文分号 `；` 或英文分号 `;`：

```text
https://mp.weixin.qq.com/s/abc123；
https://mp.weixin.qq.com/s/def456
```

## 输出结构

脚本会在 `articles/raw/` 下生成：

```text
YYYY-MM-DD_标题简写/
  article.md
  raw.html
  source.json
  images/
```

`article.md` 会自动填入：

- `Summary`
- `Research Question`
- `Core Hypothesis`
- `Signal Framework / Decision Framework` 或 `Signal / Feature Definition`
- `Code Blocks`

`article.md` 的图片区会自动写入类似：

```markdown
![image_1](images/001.jpg)
![image_2](images/002.png)
```

批量模式结束后会打印成功/失败汇总，并把失败项写入 `sources/processed/ingest_failures.txt`。

失败清单每行格式：

```text
<url>	<error_type>	<error_message>
```

## 微信风控说明

如果脚本报类似下面的错误：

```text
wechat returned a verification/blocked page instead of the article content
```

说明微信返回的是验证页，不是正文。此时建议：

1. 在浏览器中打开该链接并完成验证
2. 把完整网页另存为本地 HTML
3. 使用 `--html-file` 模式导入

## 下一步建议

- 接入 OCR 和图表摘要
- 接入 LLM 自动补 `idea_blocks`、`combination_hooks`、`brainstorm_value`
- 对 `article.md` 做分块导出，直接服务后续 RAG
